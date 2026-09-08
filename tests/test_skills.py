"""Tests de las skills: descubrimiento automático y ejecución."""
import unittest

from fakes import FakeProvider
from llmrouter import Router, UsageTracker
from llmrouter.skills import SkillRegistry, discover_skills


class SkillsTests(unittest.TestCase):
    def test_descubre_las_skills_incluidas(self):
        skills = discover_skills()
        self.assertIn("translate", skills)
        self.assertIn("summarize", skills)

    def test_registro_lista_skills_con_metadatos(self):
        registry = SkillRegistry()
        names = [s["name"] for s in registry.list()]
        self.assertIn("translate", names)

    def test_ejecuta_skill_con_router(self):
        router = Router(providers=[FakeProvider("A", priority=1, outcome="ok")], usage_tracker=UsageTracker(":memory:"))
        registry = SkillRegistry(router=router)
        out = registry.run("translate", text="hola mundo", to="inglés")
        self.assertIsInstance(out, str)
        self.assertTrue(len(out) > 0)

    def test_skill_desconocida_lanza_keyerror(self):
        registry = SkillRegistry()
        with self.assertRaises(KeyError):
            registry.run("no_existe")


if __name__ == "__main__":
    unittest.main()
