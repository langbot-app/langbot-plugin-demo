"""LLM-based listwise reranking for retrieval results.

Sends all candidate passages to an LLM in a single call, asking it to rank
them by relevance.  This avoids the need for a dedicated reranker model on
the Host side while still providing a meaningful quality boost over raw
vector-distance ordering.
"""

import logging
import re

from langbot_plugin.api.entities.builtin.provider.message import Message

logger = logging.getLogger(__name__)

# Maximum characters per candidate passage sent to the LLM.
_PASSAGE_TRUNCATE = 300

RERANK_PROMPT = """\
Given a query and candidate passages, rank the passages by relevance to the query.
Return ONLY the passage numbers in order from most relevant to least relevant.
Format: comma-separated numbers, e.g. "3,1,0,2,4"

Query: {query}

Candidates:
{candidates}

Ranking:"""


def _extract_text(msg: Message) -> str:
    """Extract plain text from an LLM response Message."""
    if isinstance(msg.content, str):
        return msg.content.strip()
    if isinstance(msg.content, list):
        return "".join(e.text for e in msg.content if e.type == "text").strip()
    return ""


def _parse_ranking(text: str, n: int) -> list[int] | None:
    """Parse a comma/space separated list of integers from LLM output.

    Returns a deduplicated list of valid indices (0..n-1), or *None* if
    parsing fails entirely (no valid indices found).
    """
    nums = re.findall(r"\d+", text)
    if not nums:
        return None

    seen: set[int] = set()
    indices: list[int] = []
    for s in nums:
        idx = int(s)
        if 0 <= idx < n and idx not in seen:
            seen.add(idx)
            indices.append(idx)
    return indices if indices else None


async def llm_rerank(
    plugin,
    llm_uuid: str,
    query: str,
    results: list[dict],
    top_k: int,
) -> list[dict]:
    """Rerank *results* using an LLM and return the top *top_k* entries.

    On any failure (LLM error, unparseable response) the function falls back
    to returning ``results[:top_k]`` so that retrieval is never blocked.
    """
    if not results:
        return results

    n = len(results)
    logger.info(f"[Rerank] LLM reranking {n} candidates for query: {query!r}")

    # Build numbered candidate list
    lines: list[str] = []
    for i, res in enumerate(results):
        text = (res.get("metadata", {}).get("text", "") or "")[:_PASSAGE_TRUNCATE]
        lines.append(f"[{i}] {text}")
    candidates_block = "\n".join(lines)

    prompt = RERANK_PROMPT.format(query=query, candidates=candidates_block)

    try:
        resp = await plugin.invoke_llm(
            llm_uuid, [Message(role="user", content=prompt)]
        )
        raw = _extract_text(resp)
        logger.info(f"[Rerank] LLM response: {raw!r}")
    except Exception as e:
        logger.warning(f"[Rerank] LLM call failed, falling back to original order: {e}")
        return results[:top_k]

    ranking = _parse_ranking(raw, n)
    if ranking is None:
        logger.warning(
            "[Rerank] Failed to parse ranking from LLM response, "
            "falling back to original order"
        )
        return results[:top_k]

    # If LLM returned fewer indices than n, append the missing ones in their
    # original order so we never silently drop results.
    if len(ranking) < n:
        remaining = [i for i in range(n) if i not in set(ranking)]
        ranking.extend(remaining)

    reranked = [results[i] for i in ranking[:top_k]]

    # Rewrite distance so downstream sorting stays consistent with LLM ranking.
    for rank, res in enumerate(reranked):
        res["distance"] = 0.01 * (rank + 1)

    logger.info(
        f"[Rerank] Done: {n} candidates → top {len(reranked)} "
        f"(order: {ranking[:top_k]})"
    )
    return reranked
