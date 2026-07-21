"""
KAEOS L2 — Chunker Transform (KAEOS Data Fabric)

Four production strategies:
1. Fixed-size chunking — fast, predictable
2. Sentence-boundary chunking — preserves semantic units
3. Recursive chunking — good general-purpose default
4. Semantic chunking — highest quality, most expensive
"""
from app.transforms.base import BaseTransformNode, TransformRecord, TransformResult
import hashlib
import logging
import asyncio

logger = logging.getLogger(__name__)

# Lazy imports
_text_splitters_loaded = False
_RecursiveCharacterTextSplitter = None
_CharacterTextSplitter = None


def _load_text_splitters():
    global _text_splitters_loaded, _RecursiveCharacterTextSplitter, _CharacterTextSplitter
    if not _text_splitters_loaded:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter, CharacterTextSplitter
            _RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter
            _CharacterTextSplitter = CharacterTextSplitter
        except ImportError:
            logger.warning("langchain_text_splitters not installed. Falling back to basic chunker.")
            _RecursiveCharacterTextSplitter = None
            _CharacterTextSplitter = None
        _text_splitters_loaded = True


class ChunkerNode(BaseTransformNode):
    """
    Splits text content into AI-ready chunks.

    Config:
        strategy: "fixed" | "sentence" | "recursive" | "semantic"
        chunk_size: int (characters) — default 500
        chunk_overlap: int — default 50
    """

    def validate_config(self) -> list[str]:
        errors = []
        strategy = self.config.get("strategy", "recursive")
        if strategy not in ("fixed", "sentence", "recursive", "semantic"):
            errors.append(f"Invalid chunking strategy: {strategy}")
        chunk_size = self.config.get("chunk_size", 500)
        if not isinstance(chunk_size, int) or chunk_size < 50:
            errors.append("chunk_size must be an integer >= 50")
        return errors

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        _load_text_splitters()

        strategy = self.config.get("strategy", "recursive")
        chunk_size = self.config.get("chunk_size", 500)
        chunk_overlap = self.config.get("chunk_overlap", 50)

        total_chunks = 0
        processed = []

        for record in records:
            text = record.text_content
            if not text:
                text = self._extract_text(record.data)
                record.text_content = text

            if not text:
                processed.append(record)
                continue

            # Chunk using enterprise LangChain splitters
            loop = asyncio.get_running_loop()
            chunks = await loop.run_in_executor(
                None,
                self._langchain_chunk,
                text, strategy, chunk_size, chunk_overlap
            )

            record.chunks = []
            for i, chunk_text in enumerate(chunks):
                chunk_id = hashlib.sha256(
                    f"{record.source_record_id}:{i}:{chunk_text[:100]}".encode()
                ).hexdigest()[:32]

                record.chunks.append({
                    "chunk_id": chunk_id,
                    "chunk_index": i,
                    "text": chunk_text,
                    "char_count": len(chunk_text),
                    "source_record_id": record.source_record_id,
                    "metadata": {
                        **record.metadata,
                        "chunk_strategy": strategy,
                        "chunk_size_config": chunk_size,
                        "total_chunks": len(chunks),
                    },
                })

            total_chunks += len(chunks)
            self.add_lineage(record, f"chunked:{strategy}:{len(chunks)}_chunks")
            processed.append(record)

        return TransformResult(
            records=processed,
            stats={
                "total_records": len(records),
                "total_chunks": total_chunks,
                "avg_chunks_per_record": total_chunks / max(len(records), 1),
                "strategy": strategy,
            },
        )

    def _langchain_chunk(self, text: str, strategy: str, chunk_size: int, overlap: int) -> list[str]:
        if _RecursiveCharacterTextSplitter is None:
            # Fallback basic chunking implementation using word boundaries
            words = text.split(" ")
            chunks = []
            curr_chunk = []
            curr_len = 0
            for w in words:
                if curr_len + len(w) + 1 > chunk_size:
                    if curr_chunk:
                        chunks.append(" ".join(curr_chunk))
                    curr_chunk = [w]
                    curr_len = len(w)
                else:
                    curr_chunk.append(w)
                    curr_len += len(w) + 1
            if curr_chunk:
                chunks.append(" ".join(curr_chunk))
            return chunks

        if strategy == "fixed":
            splitter = _CharacterTextSplitter(separator="", chunk_size=chunk_size, chunk_overlap=overlap)
        elif strategy == "sentence":
            separators = self.config.get("separators", [". ", "? ", "! ", "\n\n", "\n", " "])
            splitter = _RecursiveCharacterTextSplitter(
                separators=separators, chunk_size=chunk_size, chunk_overlap=overlap,
            )
        elif strategy == "semantic":
            try:
                from langchain_experimental.text_splitter import SemanticChunker
                # Assume an embedding service is available for semantic chunking
                # If not, fallback to recursive
                from langchain_community.embeddings import HuggingFaceEmbeddings
                embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
                splitter = SemanticChunker(embeddings)
                return splitter.split_text(text)
            except ImportError:
                logger.warning("langchain_experimental or embeddings not found, falling back to recursive chunking")
                separators = self.config.get("separators", ["\n\n", "\n", ". ", " ", ""])
                splitter = _RecursiveCharacterTextSplitter(
                    separators=separators, chunk_size=chunk_size, chunk_overlap=overlap,
                )
        else:
            separators = self.config.get("separators", ["\n\n", "\n", ". ", " ", ""])
            splitter = _RecursiveCharacterTextSplitter(
                separators=separators, chunk_size=chunk_size, chunk_overlap=overlap,
            )
        return splitter.split_text(text)



    @staticmethod
    def _extract_text(data: dict) -> str:
        text_fields = []
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 10:
                text_fields.append(f"{key}: {value}")
        return "\n\n".join(text_fields)
