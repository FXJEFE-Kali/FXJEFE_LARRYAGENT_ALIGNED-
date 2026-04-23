#!/usr/bin/env python3
"""
Show complete RAG and Model configuration reference.
"""
import json
import requests

def main():
    from production_rag import ProductionRAG, RAG_CONFIG
    from model_router import MODEL_CONFIGS, TaskType
    
    print("=" * 80)
    print("COMPLETE RAG & MODEL CONFIGURATION REFERENCE")
    print("=" * 80)
    
    # RAG Config
    print("\n📦 RAG CONFIGURATION")
    print("-" * 40)
    for key, value in RAG_CONFIG.items():
        print(f"  {key}: {value}")
    
    # Initialize RAG
    rag = ProductionRAG()
    config = rag.get_config()
    
    print("\n📊 RAG INSTANCE STATUS")
    print("-" * 40)
    print(f"  Embedding Model: {config['embedding_model']}")
    print(f"  Using Ollama Embeddings: {config['using_ollama_embeddings']}")
    print(f"  Reranker: {config['reranker_model']}")
    print(f"  Reranker Available: {config['reranker_available']}")
    print(f"  ChromaDB Available: {config['chroma_available']}")
    print(f"\n  KB Documents: {rag.kb_collection.count()}")
    print(f"  Code Documents: {rag.code_collection.count()}")
    print(f"  Conv Documents: {rag.conv_collection.count()}")
    
    # Get installed models
    print("\n🤖 INSTALLED OLLAMA MODELS")
    print("-" * 80)
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            for m in models:
                name = m["name"]
                size_gb = m.get("size", 0) / 1e9
                cfg = MODEL_CONFIGS.get(name)
                if cfg:
                    tasks = ", ".join([t.value for t in cfg.tasks][:3])
                    output = getattr(cfg, "output_limit", 4096)
                    print(f"  ✓ {name:<50} ctx:{cfg.context_limit:<8} out:{output:<6} ({size_gb:.1f}GB)")
                else:
                    print(f"  ? {name:<50} (not in MODEL_CONFIGS) ({size_gb:.1f}GB)")
    except Exception as e:
        print(f"  Error getting models: {e}")
    
    # Context limits table
    print("\n📏 CONTEXT LIMITS QUICK REFERENCE")
    print("-" * 80)
    print(f"{'Model':<45} {'Input Ctx':<12} {'Output Limit':<12} {'Tasks'}")
    print("-" * 80)
    
    priority_models = [
        "llama3.1:latest",
        "qwen3:8b",
        "llama3.2:3b",
        "mxbai-embed-large:latest",
        "nomic-embed-text:latest",
        "gpt-oss:20b",
    ]
    
    for name in priority_models:
        cfg = MODEL_CONFIGS.get(name)
        if cfg:
            tasks = ", ".join([t.value for t in cfg.tasks][:3])
            output = getattr(cfg, "output_limit", 4096)
            print(f"  {name:<43} {cfg.context_limit:<12} {output:<12} {tasks}")
    
    print("\n💡 NOTES:")
    print("  - Input Context: Max tokens for prompt + context")
    print("  - Output Limit: Max tokens for model response")
    print("  - Ollama default output: 128 tokens (set num_predict to increase)")
    print("  - To switch embeddings: delete chroma_db/ and re-index")


if __name__ == "__main__":
    main()
