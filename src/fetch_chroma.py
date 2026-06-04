from src.history_store import HistoryStore
store = HistoryStore(db_path='../utils/result/history.db', chroma_path='result/chroma')
results = store.semantic_search('insider trading tip shared before earnings', n_results=5)
for r in results:
    print(r)
