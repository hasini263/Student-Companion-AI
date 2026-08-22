import re
import math
import json
import zlib
from models.note import NoteChunk, Note

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how",
    "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the",
    "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}

DIM_SIZE = 128

def compute_vector_embedding(text):
    """
    Computes a 128-dimensional L2-normalized dense semantic vector embedding for any text string.
    Uses character n-grams and word hashing projection to capture semantic sub-patterns.
    """
    if not text:
        return [0.0] * DIM_SIZE
        
    vec = [0.0] * DIM_SIZE
    words = tokenize(text, filter_stopwords=False)
    
    for word in words:
        h_word = zlib.crc32(word.encode('utf-8')) % DIM_SIZE
        vec[h_word] += 1.5
        
        w_padded = f"#{word}#"
        for i in range(len(w_padded) - 2):
            ngram = w_padded[i:i+3]
            h_ngram = zlib.crc32(ngram.encode('utf-8')) % DIM_SIZE
            vec[h_ngram] += 0.5
            
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 5) for v in vec]
    return vec

def vector_cosine_similarity(vec1, vec2):
    """
    Computes cosine similarity between two 128-dimensional normalized float vectors.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(v1 * v2 for v1, v2 in zip(vec1, vec2))
    return max(0.0, min(1.0, dot))

def tokenize(text, filter_stopwords=False):
    """
    Cleans and tokenizes text into lowercase alphanumeric words.
    """
    if not text:
        return []
    words = re.findall(r'\b[a-z0-9]+\b', text.lower())
    if filter_stopwords:
        return [w for w in words if w not in STOP_WORDS and len(w) > 1]
    return words

def calculate_bm25_similarity(query_keywords, doc_tokens, doc_title_tokens):
    """
    Calculates BM25 sparse relevance score between query keywords and document content + title.
    """
    if not query_keywords or not doc_tokens:
        return 0.0
        
    doc_len = len(doc_tokens)
    if doc_len == 0:
        return 0.0

    score = 0.0
    doc_freq = {}
    for t in doc_tokens:
        doc_freq[t] = doc_freq.get(t, 0) + 1
        
    title_freq = {}
    for t in doc_title_tokens:
        title_freq[t] = title_freq.get(t, 0) + 1

    for q_term in set(query_keywords):
        tf = doc_freq.get(q_term, 0)
        if q_term in title_freq:
            tf += title_freq[q_term] * 3

        if tf > 0:
            tf_score = (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * (doc_len / 300.0)))
            score += tf_score

    normalized = score / len(set(query_keywords))
    return round(normalized, 4)

def chunk_text(text, chunk_size=600, overlap=150):
    """
    Splits text into chunks of roughly chunk_size characters with overlap.
    """
    chunks = []
    if not text:
        return chunks
        
    text_length = len(text)
    start = 0
    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            last_space = text.rfind(' ', start, end)
            if last_space != -1 and last_space > start + (chunk_size // 2):
                end = last_space
        chunks.append(text[start:end].strip())
        start = end - overlap if end < text_length else text_length
        if start <= 0 or start >= text_length:
            break
    return [c for c in chunks if len(c) > 10]

def retrieve_context(user_id, query, top_k=4):
    """
    Retrieves the most contextually relevant chunks using Hybrid Search (Vector Embeddings + BM25)
    and Reciprocal Rank Fusion (RRF).
    Returns a list of dicts: [{'title': note_title, 'content': chunk_text, 'score': hybrid_similarity}]
    """
    from extensions import db
    from models.note import Note, NoteChunk
    
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        return []
        
    results = db.session.query(NoteChunk, Note.title).join(Note, NoteChunk.note_id == Note.id).filter(Note.user_id == user_id_int).all()
    if not results:
        return []
        
    query_keywords = tokenize(query, filter_stopwords=True)
    if not query_keywords:
        query_keywords = tokenize(query, filter_stopwords=False)
        if not query_keywords:
            return []

    # 1. Compute Query Dense Embedding
    query_vec = compute_vector_embedding(query)

    # 2. Score chunks with both Dense Semantic Cosine + Sparse BM25
    candidates = []
    for chunk, note_title in results:
        if chunk.embedding:
            try:
                chunk_vec = json.loads(chunk.embedding)
            except Exception:
                chunk_vec = compute_vector_embedding(f"{note_title}\n{chunk.content}")
        else:
            chunk_vec = compute_vector_embedding(f"{note_title}\n{chunk.content}")
            try:
                chunk.embedding = json.dumps(chunk_vec)
                db.session.commit()
            except Exception:
                pass

        dense_sim = vector_cosine_similarity(query_vec, chunk_vec)
        doc_tokens = tokenize(chunk.content, filter_stopwords=False)
        title_tokens = tokenize(note_title, filter_stopwords=False)
        sparse_sim = calculate_bm25_similarity(query_keywords, doc_tokens, title_tokens)
        
        if dense_sim > 0.1 or sparse_sim > 0.05:
            candidates.append({
                "chunk": chunk,
                "title": note_title,
                "content": chunk.content,
                "dense_score": dense_sim,
                "sparse_score": sparse_sim
            })

    if not candidates:
        return []

    # 3. Reciprocal Rank Fusion (RRF)
    dense_sorted = sorted(candidates, key=lambda x: x["dense_score"], reverse=True)
    for rank, item in enumerate(dense_sorted, 1):
        item["dense_rank"] = rank

    sparse_sorted = sorted(candidates, key=lambda x: x["sparse_score"], reverse=True)
    for rank, item in enumerate(sparse_sorted, 1):
        item["sparse_rank"] = rank

    rrf_constant = 60
    for item in candidates:
        rrf = (1.0 / (rrf_constant + item["dense_rank"])) + (1.0 / (rrf_constant + item["sparse_rank"]))
        combined = round((item["dense_score"] * 0.6) + (item["sparse_score"] * 0.4), 4)
        item["score"] = max(combined, round(rrf * 30, 4))

    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    output = []
    for item in candidates[:top_k]:
        output.append({
            "title": item["title"],
            "content": item["content"],
            "score": item["score"]
        })
    return output


