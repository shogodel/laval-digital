"""Unit tests for core/base_agent.py pure functions."""
from core.base_agent import BaseAgent


class TestDetectLanguage:
    def test_english_short_greeting(self):
        text = "hello how are you"
        assert BaseAgent._detect_language(text) == "en"

    def test_english_no_french_keywords(self):
        text = "I need help with SEO for my business"
        assert BaseAgent._detect_language(text) == "en"

    def test_french_clear(self):
        text = "Bonjour, je voudrais de l'aide pour mon SEO s'il vous plaît"
        assert BaseAgent._detect_language(text) == "fr"

    def test_french_mixed(self):
        text = "bonjour je cherche des informations sur le marketing"
        assert BaseAgent._detect_language(text) == "fr"

    def test_french_threshold_three_keywords(self):
        text = "bonjour comment ça va"
        assert BaseAgent._detect_language(text) == "fr"

    def test_french_boundary_three_keywords(self):
        text = "bonjour comment ça va merci"
        assert BaseAgent._detect_language(text) == "fr"

    def test_empty_string(self):
        assert BaseAgent._detect_language("") == "en"

    def test_numbers_and_symbols(self):
        assert BaseAgent._detect_language("123 !@#") == "en"


class TestParseConfidence:
    def test_normal_confidence(self):
        draft = "Some output\nCONFIDENCE: 85\nREASONING: I am confident"
        assert BaseAgent._parse_confidence(draft) == 0.85

    def test_max_confidence(self):
        draft = "Some output\nCONFIDENCE: 100"
        assert BaseAgent._parse_confidence(draft) == 1.0

    def test_min_confidence(self):
        draft = "Some output\nCONFIDENCE: 0"
        assert BaseAgent._parse_confidence(draft) == 0.0

    def test_no_confidence(self):
        draft = "Some output without confidence"
        assert BaseAgent._parse_confidence(draft) is None

    def test_confidence_without_reasoning(self):
        draft = "Draft text\nCONFIDENCE: 42"
        assert BaseAgent._parse_confidence(draft) == 0.42

    def test_confidence_colon_variations(self):
        draft = "Text\nCONFIDENCE : 75"
        assert BaseAgent._parse_confidence(draft) == 0.75

    def test_extra_whitespace(self):
        draft = "Text\nCONFIDENCE:   90  \nREASONING:   solid"
        assert BaseAgent._parse_confidence(draft) == 0.9


class TestStripConfidenceMetadata:
    def test_removes_confidence_and_reasoning(self):
        draft = "Main content\nCONFIDENCE: 85\nREASONING: good"
        result = BaseAgent._strip_confidence_metadata(draft)
        assert result == "Main content"

    def test_only_confidence(self):
        draft = "Main content\nCONFIDENCE: 85"
        result = BaseAgent._strip_confidence_metadata(draft)
        assert result == "Main content"

    def test_no_metadata(self):
        draft = "Just content"
        result = BaseAgent._strip_confidence_metadata(draft)
        assert result == "Just content"

    def test_confidence_in_middle_not_stripped(self):
        draft = "CONFIDENCE is important\nfor confidence building\nCONFIDENCE: 50"
        result = BaseAgent._strip_confidence_metadata(draft)
        assert "CONFIDENCE is important" in result

    def test_multiline_content(self):
        draft = "Line 1\nLine 2\nLine 3\nCONFIDENCE: 30\nREASONING: low"
        result = BaseAgent._strip_confidence_metadata(draft)
        assert result == "Line 1\nLine 2\nLine 3"


class TestGetLanguageInstruction:
    def test_english_instruction(self):
        text = "hello"
        instruction = BaseAgent._get_language_instruction(text)
        assert "Respond in English" in instruction

    def test_french_instruction(self):
        text = "bonjour je veux de l'aide merci"
        instruction = BaseAgent._get_language_instruction(text)
        assert "respond entirely in french" in instruction.lower()
