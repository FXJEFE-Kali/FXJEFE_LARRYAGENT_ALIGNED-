#!/usr/bin/env python3
"""
Test Agent V2 with XAU price search using RAG + MCP tools
"""
import asyncio
import sys

def main():
    print("=" * 60)
    print(" AGENT V2 - XAU PRICE TEST (RAG + MCP + Web Search)")
    print("=" * 60)
    
    from agent_v2 import EnhancedAgent
    
    agent = EnhancedAgent()
    
    # Show RAG stats
    if agent.rag:
        stats = agent.rag.get_stats()
        print(f"\n📚 RAG Status: {stats.get('total_documents', 0)} documents indexed")
        print(f"   Collections: {stats.get('collections', {})}")
    else:
        print("\n⚠️ RAG not available")
    
    # Show MCP tools
    if agent.mcp:
        tools = agent.mcp.get_available_tools()
        print(f"\n🔧 MCP Tools Available: {tools}")
    else:
        print("\n⚠️ MCP not available")
    
    # Test web search via Brave Search MCP
    print("\n" + "=" * 60)
    print(" Testing Brave Search MCP for XAU prices...")
    print("=" * 60)
    
    if agent.mcp:
        try:
            # Use Brave Search MCP tool via the brave_search attribute
            if agent.mcp.brave_search.available:
                search_result = agent.mcp.brave_search.web_search(
                    query="XAU gold price today February 2026 USD per ounce",
                    count=5
                )
                print(f"\n[Search] Brave Search Results:")
                if isinstance(search_result, dict):
                    results = search_result.get('results', search_result.get('web', {}).get('results', []))
                    if results:
                        for i, r in enumerate(results[:5], 1):
                            title = r.get('title', 'No title')
                            desc = r.get('description', r.get('snippet', 'No description'))[:200]
                            url = r.get('url', 'No URL')
                            print(f"\n  {i}. {title}")
                            print(f"     {desc}...")
                            print(f"     URL: {url}")
                    else:
                        print(f"  Raw result: {str(search_result)[:500]}")
                else:
                    print(f"  {search_result}")
            else:
                print("  Brave Search not available - check BRAVE_API_KEY")
        except Exception as e:
            print(f"  Brave Search error: {e}")
            import traceback
            traceback.print_exc()
    
    # Now test the full agent chat with RAG context
    print("\n" + "=" * 60)
    print(" Testing Full Agent Query (RAG + MCP + Context)...")
    print("=" * 60)
    
    query = "What is the current XAU/USD gold price today? Use web search to find the latest price."
    print(f"\n📝 Query: {query}")
    
    # Run async process_query
    response = asyncio.run(agent.process_query(query))
    print(f"\n🤖 Agent Response:\n{response}")
    
    # Test RAG retrieval specifically
    print("\n" + "=" * 60)
    print(" Testing RAG Context Retrieval...")
    print("=" * 60)
    
    if agent.rag:
        try:
            context = agent.rag.get_context_for_query("gold price trading XAU", max_tokens=500)
            if context:
                print(f"\n📖 RAG Context Retrieved ({len(context)} chars):")
                print(f"   {context[:300]}..." if len(context) > 300 else f"   {context}")
            else:
                print("   No relevant context found in RAG (expected if no finance docs indexed)")
        except Exception as e:
            print(f"   RAG error: {e}")
    
    print("\n" + "=" * 60)
    print(" ✅ TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
