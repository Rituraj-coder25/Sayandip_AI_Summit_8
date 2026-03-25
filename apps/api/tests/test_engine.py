import pytest

from apps.api.core.intelligence.classifier import KeywordDomainClassifier
from apps.api.core.intelligence.india_scorer import IndiaRelevanceScorer
from apps.api.core.ontology.relation_extractor import RelationExtractor


def test_classifier_detects_domain_and_severity():
    classifier = KeywordDomainClassifier(model_dir="does-not-exist")
    result = classifier.classify("Major earthquake near Nepal raises alert levels")
    assert result.domain in {"climate", "geopolitics", "defense"}
    assert 0 <= result.severity <= 100


def test_india_relevance_scores_neighbor_events_higher():
    scorer = IndiaRelevanceScorer()
    score = scorer.score("Earthquake near Nepal may affect India", latitude=27.7, longitude=85.3)
    assert score >= 40


def test_relation_extractor_links_entities():
    extractor = RelationExtractor()
    relations = extractor.extract(
        "India met Nepal for border coordination",
        [{"text": "India"}, {"text": "Nepal"}],
    )
    assert relations
    assert relations[0]["subject"] == "India"
