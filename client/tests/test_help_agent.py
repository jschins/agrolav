import tempfile
import unittest
from pathlib import Path

from app.help_agent import answer_question, documentation_files, repo_root


class HelpAgentTests(unittest.TestCase):
    def test_reads_root_readme_and_documentation(self) -> None:
        root = repo_root()
        rels = {p.relative_to(root).as_posix() for p in documentation_files(root)}
        self.assertIn("README.md", rels)
        self.assertTrue(any(name.startswith("documentation/") for name in rels))

    def test_login_question_comes_from_root_readme(self) -> None:
        out = answer_question("how do I log in?")
        self.assertEqual(out["sources"], ["README.md"])
        self.assertIn("login", str(out["answer"]).lower())

    def test_dutch_logout_question_hits_readme(self) -> None:
        out = answer_question("hoe log ik uit?")
        self.assertEqual(out["sources"], ["README.md"])
        self.assertIn("logout", str(out["answer"]).lower())

    def test_operator_detail_comes_from_documentation(self) -> None:
        out = answer_question("what is FILELISTONLY?")
        self.assertTrue(out["sources"])
        self.assertNotEqual(out["sources"], ["README.md"])
        self.assertTrue(
            any(str(src).startswith("documentation/") for src in out["sources"])
        )

    def test_unknown_question_says_so(self) -> None:
        out = answer_question("quantum flux capacitor calibration")
        self.assertEqual(out["sources"], [])
        self.assertIn("don't find", str(out["answer"]))

    def test_prefers_readme_over_a_weaker_doc_mention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Guide\n\n## Log in\n\nEnter the password on the login page.\n",
                encoding="utf-8",
            )
            docs = root / "documentation"
            docs.mkdir()
            (docs / "deployment.md").write_text(
                "# Deploy\n\nThe password is stored in the hub env file.\n",
                encoding="utf-8",
            )
            out = answer_question("where do I enter the password to log in?", root)
            self.assertEqual(out["sources"][0], "README.md")


if __name__ == "__main__":
    unittest.main()
