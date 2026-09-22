import tempfile
import unittest
from pathlib import Path

from app.help_agent import answer_question


class HelpAgentTests(unittest.TestCase):
    def test_login_question_comes_from_root_readme(self) -> None:
        out = answer_question("how do I log in?")
        self.assertEqual(out["sources"], ["README.md"])
        self.assertIn("password", str(out["answer"]).lower())
        self.assertNotIn("{", str(out["answer"]))

    def test_dutch_logout_question_hits_readme(self) -> None:
        out = answer_question("hoe log ik uit?")
        self.assertEqual(out["sources"], ["README.md"])
        self.assertIn("logout", str(out["answer"]).lower())

    def test_body_words_and_other_files_do_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Guide\n\n## Log in\n\nEnter the password on the login page.\n"
                "{portal}\n",
                encoding="utf-8",
            )
            docs = root / "documentation"
            docs.mkdir()
            (docs / "deployment.md").write_text(
                "# Deploy\n\nFILELISTONLY is an operator switch.\n",
                encoding="utf-8",
            )
            out = answer_question("where is the password and what is FILELISTONLY?", root)
            self.assertEqual(out["sources"], [])
            self.assertIn("don't find", str(out["answer"]))

    def test_bracket_term_returns_its_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Guide\n\n## Log in\n\nEnter the password on the login page.\n"
                "{password, log in}\n",
                encoding="utf-8",
            )
            out = answer_question("where do I enter the password to log in?", root)
            self.assertEqual(out["sources"], ["README.md"])
            self.assertIn("password", str(out["answer"]).lower())
            self.assertNotIn("{password", str(out["answer"]))

    def test_discarded_phrases_are_not_counted(self) -> None:
        out = answer_question("how do I get to")
        self.assertEqual(out["sources"], [])
        kept = answer_question("how do I log in?")
        self.assertEqual(kept["sources"], ["README.md"])
        self.assertIn("password", str(kept["answer"]).lower())

    def test_unknown_question_says_so(self) -> None:
        out = answer_question("quantum flux capacitor calibration")
        self.assertEqual(out["sources"], [])
        self.assertIn("don't find", str(out["answer"]))


if __name__ == "__main__":
    unittest.main()
