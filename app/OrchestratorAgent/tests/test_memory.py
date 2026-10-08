import unittest

from memory import AgentCoreInvestigationMemory


class FakeSession:
    def __init__(self):
        self.namespaces = []

    def search_long_term_memories(self, query, namespace_path, **_):
        self.namespaces.append(namespace_path)
        return [{"namespace": namespace_path, "content": f"record from {namespace_path}"}]


class MemoryAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_planning_retrieval_includes_session_summary_and_past_episodes(self):
        memory = AgentCoreInvestigationMemory("mem-1", actor_id="me")
        session = FakeSession()
        memory._session = lambda context_id: session

        records = await memory.retrieve_for_planning("ctx-1", "why did revenue fall?")

        self.assertEqual(["investigations/me/summaries/ctx-1", "investigations/me/episodes"],
                         session.namespaces)
        self.assertEqual(2, len(records))


if __name__ == "__main__":
    unittest.main()
