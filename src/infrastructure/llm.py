"""
LLM API wrapper with multi-provider fallback strategy.

2025 Update: Claude Haiku → Cerebras → DeepSeek
- Primary: Claude Haiku 4.5 ($1/$5 per M tokens with 90% prompt caching - best quality)
- Backup: Cerebras (Llama 3.1 70B - 2000 tok/sec, 30M tokens/month free, VPN-friendly)
- Final Fallback: DeepSeek ($0.28/M tokens - ultra cheap)
"""

import os
import time
import logging
from typing import List, Dict, Optional, Any, Callable
from openai import OpenAI

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)


class LLMProvider:
    """Multi-provider LLM with automatic fallback and token tracking.

    Provides unified interface to multiple LLM providers with intelligent fallback:
    1. Claude Haiku 3.5 (primary - best quality, prompt caching for 90% savings)
    2. Cerebras Llama 3.1 70B (backup - fastest free tier)
    3. DeepSeek (final fallback - ultra cheap)

    Includes automatic rate limit handling with exponential backoff retry logic
    and cumulative token usage tracking across all providers.

    Attributes:
        anthropic_client: Anthropic client for Claude (if available)
        cerebras_client: OpenAI-compatible client for Cerebras
        deepseek_client: OpenAI-compatible client for DeepSeek
        total_input_tokens: Cumulative input tokens across all calls
        total_output_tokens: Cumulative output tokens across all calls
        total_cached_tokens: Cumulative cached tokens (Claude only)
    """

    def __init__(
        self,
        cerebras_api_key: Optional[str] = None,
        deepseek_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None
    ) -> None:
        """
        Initialize LLM providers with API keys.

        Loads API keys from arguments or environment variables (CEREBRAS_API_KEY,
        DEEPSEEK_API_KEY, ANTHROPIC_API_KEY). Initializes only
        providers with valid API keys. Warns if no providers are available.

        Args:
            cerebras_api_key: Cerebras API key (backup). Defaults to CEREBRAS_API_KEY env var.
            deepseek_api_key: DeepSeek API key (fallback). Defaults to DEEPSEEK_API_KEY env var.
            anthropic_api_key: Anthropic API key (primary). Defaults to ANTHROPIC_API_KEY env var.
        """
        # Get API keys from environment if not provided
        self.cerebras_api_key: Optional[str] = cerebras_api_key or os.getenv("CEREBRAS_API_KEY")
        self.deepseek_api_key: Optional[str] = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
        self.anthropic_api_key: Optional[str] = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")

        # Initialize clients
        self.cerebras_client: Optional[OpenAI] = None
        self.deepseek_client: Optional[OpenAI] = None
        self.anthropic_client: Optional[Any] = None

        # Token usage tracking
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.total_web_searches: int = 0  # Track web search API calls

        self._setup_providers()

    def _setup_providers(self) -> None:
        """Set up available LLM providers.

        Initializes clients for each configured provider in priority order.
        Logs success/warning for each provider. No exception raised if provider
        initialization fails - that provider is simply skipped.
        """
        # Claude Haiku (primary - best quality with prompt caching)
        if self.anthropic_api_key and ANTHROPIC_AVAILABLE:
            try:
                self.anthropic_client = Anthropic(api_key=self.anthropic_api_key)
                logger.info("✓ Claude Haiku provider initialized (primary)")
            except Exception as e:
                logger.warning(f"Failed to initialize Claude: {e}")
        elif self.anthropic_api_key and not ANTHROPIC_AVAILABLE:
            logger.warning("Anthropic API key provided but 'anthropic' package not installed. Run: pip install anthropic")

        # Cerebras (backup - fastest free tier)
        if self.cerebras_api_key:
            try:
                self.cerebras_client = OpenAI(
                    api_key=self.cerebras_api_key,
                    base_url="https://api.cerebras.ai/v1"
                )
                logger.info("✓ Cerebras provider initialized (backup)")
            except Exception as e:
                logger.warning(f"Failed to initialize Cerebras: {e}")

        # DeepSeek (final fallback - ultra cheap)
        if self.deepseek_api_key:
            try:
                self.deepseek_client = OpenAI(
                    api_key=self.deepseek_api_key,
                    base_url="https://api.deepseek.com"
                )
                logger.info("✓ DeepSeek provider initialized (final fallback)")
            except Exception as e:
                logger.warning(f"Failed to initialize DeepSeek: {e}")

        # Check if at least one provider is available
        if not any([self.cerebras_client, self.deepseek_client, self.anthropic_client]):
            logger.warning("⚠️  No LLM providers configured. Set API keys in environment.")

    def _call_with_retry(self, provider_name: str, call_fn: Callable[[], str], max_retries: int = 2) -> str:
        """
        Call LLM provider with exponential backoff retry for rate limits.

        Automatically retries on rate limit errors (429, quota exceeded, etc.)
        with exponential backoff: 1s, 2s, 4s. Non-rate-limit errors are raised
        immediately without retry.

        Args:
            provider_name: Name of provider for logging and error messages
            call_fn: Callable that executes the LLM provider call. Must return response text.
            max_retries: Maximum number of retry attempts (default: 2)

        Returns:
            Response text from the LLM provider

        Raises:
            Exception: Original exception from provider if not a rate limit error
                       or if all retry attempts are exhausted
        """
        for attempt in range(max_retries + 1):
            try:
                return call_fn()
            except Exception as e:
                error_str = str(e).lower()

                # Check if it's a rate limit error
                is_rate_limit = any(term in error_str for term in [
                    'rate limit', 'rate_limit', 'ratelimit',
                    'quota', 'too many requests', '429'
                ])

                if is_rate_limit and attempt < max_retries:
                    wait_time = (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"{provider_name} rate limit hit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                # Not a rate limit or out of retries
                raise e

        # This should never be reached due to the raise above, but mypy needs it
        raise RuntimeError(f"{provider_name}: All retry attempts failed")

    def generate(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None
    ) -> Optional[str]:
        """
        Generate response with automatic fallback and rate limit handling.

        Tries providers in priority order:
        1. Claude Haiku (with prompt caching + optional web search)
        2. Cerebras (fastest)
        3. DeepSeek (ultra cheap)

        Skips unavailable providers and logs all attempts. Tracks token usage
        including cache hits for Claude.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      Supported roles: 'system', 'user', 'assistant'
            max_tokens: Maximum tokens to generate (default: 1024)
            temperature: Sampling temperature 0.0-1.0 (default: 0.7)
                        Lower = more deterministic, higher = more creative
            tools: Optional list of tools (e.g., Claude's web search tool).
                   Only supported by Claude provider.
                   Example: [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]

        Returns:
            Generated text response string, or None if all providers fail

        Example:
            >>> llm = LLMProvider()
            >>> messages = [
            ...     {"role": "system", "content": "You are helpful"},
            ...     {"role": "user", "content": "Say hello"}
            ... ]
            >>> response = llm.generate(messages, max_tokens=50)
            >>> print(response)
            Hello! How can I help you today?

            >>> # With web search
            >>> response = llm.generate(
            ...     messages,
            ...     max_tokens=1024,
            ...     tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
            ... )
        """
        # Try Claude Haiku first (best quality with prompt caching)
        if self.anthropic_client:
            try:
                logger.debug("Trying Claude Haiku 4.5 with prompt caching...")

                def claude_call():
                    # Convert messages to Anthropic format with prompt caching
                    # Mark system message for caching (saves 90% on repeated context)
                    anthropic_messages = []
                    system_content = None

                    for msg in messages:
                        if msg["role"] == "system":
                            # Cache system prompts (RAG context)
                            system_content = [
                                {
                                    "type": "text",
                                    "text": msg["content"],
                                    "cache_control": {"type": "ephemeral"}
                                }
                            ]
                        else:
                            anthropic_messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })

                    # Call Claude with prompt caching (and optional tools like web search)
                    create_params = {
                        "model": "claude-3-5-haiku-20241022",
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": system_content if system_content else [],
                        "messages": anthropic_messages
                    }

                    # Add tools if provided (e.g., web search)
                    if tools:
                        create_params["tools"] = tools
                        logger.debug(f"Using tools: {[t.get('type') for t in tools]}")

                    response = self.anthropic_client.messages.create(**create_params)

                    # Track token usage
                    usage = response.usage
                    self.total_input_tokens += usage.input_tokens
                    self.total_output_tokens += usage.output_tokens
                    cached = getattr(usage, 'cache_read_input_tokens', 0)
                    self.total_cached_tokens += cached

                    # Track web search usage if tools were provided
                    if tools:
                        # Count web search tool uses from response
                        for block in response.content:
                            if hasattr(block, 'type') and block.type == 'tool_use':
                                if hasattr(block, 'name') and block.name == 'web_search':
                                    self.total_web_searches += 1
                                    logger.debug(f"Web search used (total: {self.total_web_searches})")

                    # Handle tool use responses (e.g., web search)
                    # When tools are used, response.content is a list of blocks
                    # that can include TextBlock and ToolUseBlock objects
                    text_parts = []
                    for block in response.content:
                        if hasattr(block, 'text'):
                            # TextBlock - extract the text content
                            text_parts.append(block.text)
                        elif hasattr(block, 'type') and block.type == 'tool_use':
                            # ToolUseBlock - skip, Claude will use tool results internally
                            logger.debug(f"Tool used: {block.name}")

                    # If we got text content, return it
                    if text_parts:
                        return ' '.join(text_parts)

                    # If no text but stop_reason is end_turn, Claude finished with tools
                    # Need to continue the conversation to get the final text response
                    if response.stop_reason == 'end_turn' and not text_parts:
                        # Continue conversation to get Claude's final answer
                        anthropic_messages.append({
                            "role": "assistant",
                            "content": response.content
                        })

                        # Ask Claude to provide the final answer
                        anthropic_messages.append({
                            "role": "user",
                            "content": "Please provide your answer based on the search results."
                        })

                        create_params["messages"] = anthropic_messages
                        followup_response = self.anthropic_client.messages.create(**create_params)

                        # Track followup tokens
                        followup_usage = followup_response.usage
                        self.total_input_tokens += followup_usage.input_tokens
                        self.total_output_tokens += followup_usage.output_tokens
                        cached = getattr(followup_usage, 'cache_read_input_tokens', 0)
                        self.total_cached_tokens += cached

                        # Track web searches in followup
                        if tools:
                            for block in followup_response.content:
                                if hasattr(block, 'type') and block.type == 'tool_use':
                                    if hasattr(block, 'name') and block.name == 'web_search':
                                        self.total_web_searches += 1
                                        logger.debug(f"Web search used in followup (total: {self.total_web_searches})")

                        # Extract text from followup
                        for block in followup_response.content:
                            if hasattr(block, 'text'):
                                text_parts.append(block.text)

                        return ' '.join(text_parts) if text_parts else ""

                    return ""

                result = self._call_with_retry("Claude Haiku", claude_call)

                # Log token usage with cache hit rate
                if self.total_cached_tokens > 0:
                    cache_rate = (self.total_cached_tokens / max(self.total_input_tokens, 1)) * 100
                    logger.info(f"✓ Claude Haiku | Tokens: {self.total_input_tokens:,} input, "
                               f"{self.total_output_tokens:,} output, {self.total_cached_tokens:,} cached ({cache_rate:.1f}% cache hit)")
                else:
                    logger.info(f"✓ Claude Haiku | Tokens: {self.total_input_tokens:,} input, {self.total_output_tokens:,} output")

                return result

            except Exception as e:
                logger.warning(f"Claude Haiku failed: {e}. Trying backup...")

        # Try Cerebras (backup - fast and free)
        if self.cerebras_client:
            try:
                logger.debug("Trying Cerebras (Llama 3.1 70B)...")

                def cerebras_call():
                    response = self.cerebras_client.chat.completions.create(
                        model="llama3.1-70b",
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature
                    )
                    return response.choices[0].message.content

                result = self._call_with_retry("Cerebras", cerebras_call)
                logger.info("✓ Response from Cerebras")
                return result

            except Exception as e:
                logger.warning(f"Cerebras failed: {e}. Trying final fallback...")

        # Try DeepSeek (final fallback - ultra cheap)
        if self.deepseek_client:
            try:
                logger.debug("Trying DeepSeek...")

                def deepseek_call():
                    response = self.deepseek_client.chat.completions.create(
                        model="deepseek-chat",
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature
                    )
                    return response.choices[0].message.content

                result = self._call_with_retry("DeepSeek", deepseek_call)
                logger.info("✓ Response from DeepSeek")
                return result

            except Exception as e:
                logger.error(f"DeepSeek failed: {e}")

        logger.error("❌ All LLM providers failed")
        return None

    def get_usage_stats(self) -> Dict[str, Any]:
        """
        Get cumulative token usage statistics across all providers.

        Calculates cost estimates based on Claude Haiku pricing:
        - Input tokens: $1.00 per 1M tokens
        - Output tokens: $5.00 per 1M tokens
        - Cached input tokens: $0.10 per 1M tokens (90% discount)
        - Web searches: $10.00 per 1K searches ($0.01 per search)

        Returns:
            Dictionary with keys:
                'input_tokens': Total input tokens
                'output_tokens': Total output tokens
                'cached_tokens': Total cached tokens (Claude only)
                'web_searches': Total web search API calls
                'cache_hit_rate': Percentage string (e.g., "45.2%")
                'estimated_cost': Estimated total cost string (e.g., "$0.0234")
                'cache_savings': Savings from prompt caching (e.g., "$0.0156")

        Example:
            >>> llm = LLMProvider()
            >>> llm.generate([{"role": "user", "content": "Hello"}])
            >>> stats = llm.get_usage_stats()
            >>> print(f"Cost: {stats['estimated_cost']}, Cache savings: {stats['cache_savings']}")
        """
        # Claude Haiku 4.5 pricing (Dec 2025)
        # Input: $1.00/1M tokens, Output: $5.00/1M tokens, Cached: $0.10/1M tokens
        # Web search: $10.00/1K searches ($0.01 per search)
        non_cached_input = max(0, self.total_input_tokens - self.total_cached_tokens)

        non_cached_cost = (non_cached_input * 1.00 / 1_000_000)
        cached_cost = (self.total_cached_tokens * 0.10 / 1_000_000)
        output_cost = (self.total_output_tokens * 5.00 / 1_000_000)
        web_search_cost = (self.total_web_searches * 10.00 / 1_000)  # $10 per 1K searches

        total_cost = non_cached_cost + cached_cost + output_cost + web_search_cost

        # Calculate how much we WOULD have paid without caching
        cost_without_cache = (self.total_input_tokens * 1.00 / 1_000_000) + output_cost + web_search_cost
        cache_savings = cost_without_cache - total_cost

        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cached_tokens": self.total_cached_tokens,
            "web_searches": self.total_web_searches,
            "cache_hit_rate": f"{(self.total_cached_tokens / max(self.total_input_tokens, 1)) * 100:.1f}%",
            "estimated_cost": f"${total_cost:.4f}",
            "cache_savings": f"${cache_savings:.4f}"
        }

def create_rag_prompt(query: str, platforms: List[Dict]) -> List[Dict[str, str]]:
    """
    Create RAG prompt with context from retrieved platforms.

    Builds a system prompt with guardrails to keep the assistant focused on
    PoC platforms in tech/outdoor spaces, plus a user prompt with platform
    context and the user's query.

    Args:
        query: User's natural language question
        platforms: List of retrieved platform dictionaries with fields like
                  'name', 'type', 'focus_area', 'description', 'website', etc.

    Returns:
        List of two message dicts:
            - System message with instructions and boundaries
            - User message with platform context and query

    Example:
        >>> platforms = [{"name": "Outdoor Afro", "type": "Outdoor/Travel", ...}]
        >>> messages = create_rag_prompt("Black hiking communities?", platforms)
        >>> assert messages[0]["role"] == "system"
        >>> assert "Black hiking communities" in messages[1]["content"]
    """
    # Build context from platforms
    context_parts = []
    for i, platform in enumerate(platforms, 1):
        context_parts.append(
            f"{i}. **{platform['name']}**\n"
            f"   Type: {platform['type']}\n"
            f"   Focus: {platform['focus_area']}\n"
            f"   Description: {platform['description']}\n"
            f"   Website: {platform['website']}\n"
            f"   Programs: {platform['key_programs']}\n"
            f"   Community Size: {platform['community_size']}\n"
            f"   Location: {platform['geographic_focus']}\n"
        )

    context = "\n".join(context_parts)

    # System prompt with guardrails
    system_prompt = """You are a specialized assistant that helps people discover platforms and communities for People of Color (PoC) in tech and outdoor/travel spaces.

IMPORTANT BOUNDARIES:
- ONLY answer questions about PoC platforms in tech or outdoor/travel
- ONLY use information from the provided platform context below
- If asked about unrelated topics (politics, general advice, other subjects), politely redirect: "I'm specifically designed to help discover PoC platforms in tech and outdoor/travel. Could you ask about those topics instead?"
- Do NOT make up or hallucinate platform information
- Do NOT provide platforms that aren't in the context

Your role:
- Answer questions about platforms based ONLY on the provided context
- Be friendly, encouraging, and supportive
- Highlight relevant platforms with their key features
- Suggest follow-up questions about platforms when appropriate
- If no relevant platforms are found, politely explain and suggest broadening the search within tech/outdoor domains

Format your responses:
- Use clear, conversational language
- List platforms with brief descriptions from the context
- Include website links when mentioning platforms
- Keep responses concise (2-4 paragraphs max)
- Stay focused on helping users discover relevant communities
"""

    # User prompt with context
    user_prompt = f"""Based on these platforms:

{context}

Question: {query}

Please provide a helpful response that highlights the most relevant platforms and their key features."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    llm = LLMProvider()

    test_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hello in one sentence."}
    ]

    response = llm.generate(test_messages, max_tokens=100)

    if response:
        print(f"\nLLM Response:\n{response}")
    else:
        print("\n⚠️  No LLM providers available. Set API keys in environment.")
