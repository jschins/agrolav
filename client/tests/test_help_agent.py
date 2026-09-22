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

    def test_hit_returns_the_whole_section_not_one_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Guide\n\n"
                "## Edit Terms\n\n"
                "Open the term window.\n\n"
                "The window has four columns.\n"
                "{en: edit terms, column}\n\n"
                "### How terms match\n\n"
                "A term matches a whole word.\n\n"
                "Priority comes last.\n"
                "{en: word, priority}\n",
                encoding="utf-8",
            )
            edit = answer_question("edit terms", root)
            self.assertIn("four columns", str(edit["answer"]))
            self.assertNotIn("whole word", str(edit["answer"]))
            match = answer_question("what is the priority of a word", root)
            self.assertIn("whole word", str(match["answer"]))
            self.assertIn("Priority comes last", str(match["answer"]))
            self.assertNotIn("four columns", str(match["answer"]))

    def test_two_hits_outweigh_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "## Phrase\n\nOne phrase.\n{en: four columns}\n\n"
                "## Words\n\nTwo words.\n{en: four,columns}\n\n"
                "## Single\n\nOnly columns.\n{en: columns}\n",
                encoding="utf-8",
            )
            answer = str(answer_question("four columns", root)["answer"])
            self.assertLess(answer.index("Two words"), answer.index("One phrase"))
            self.assertLess(answer.index("Two words"), answer.index("Only columns"))

    def test_lower_scoring_sections_follow_the_highest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "## Alpha\n\nAlpha body.\n{en: shared}\n\n"
                "## Beta\n\nBeta body.\n{en: shared, extra}\n",
                encoding="utf-8",
            )
            out = answer_question("shared extra", root)
            answer = str(out["answer"])
            self.assertLess(answer.index("Beta body"), answer.index("Alpha body"))

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

    def test_hidden_preamble_discards_and_brackets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "<!-- {discard-en:how,do,i} -->\n\n"
                "# Guide\n\n"
                "## Log in\n\n"
                "Enter the password.\n"
                "<!-- {en:password,log in} -->\n"
                "\n---\n\n"
                "## Later\n\n"
                "After login the matrix is shown.\n"
                "<!-- {en:matrix} -->\n",
                encoding="utf-8",
            )
            out = answer_question("how do I log in?", root)
            answer = str(out["answer"])
            self.assertIn("password", answer.lower())
            self.assertNotIn("{", answer)
            self.assertNotIn("matrix", answer.lower())

    def test_unknown_question_says_so(self) -> None:
        out = answer_question("quantum flux capacitor calibration")
        self.assertEqual(out["sources"], [])
        self.assertIn("don't find", str(out["answer"]))


if __name__ == "__main__":
    unittest.main()
