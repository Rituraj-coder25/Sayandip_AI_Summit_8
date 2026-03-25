from __future__ import annotations

import logging
import re

logger = logging.getLogger("goe.ner")

_nlp = None
RELEVANT_LABELS = {"GPE", "ORG", "PERSON", "NORP", "EVENT", "LOC", "FAC", "PRODUCT", "LAW"}


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy

            try:
                _nlp = spacy.load("en_core_web_trf")
                logger.info("spaCy: en_core_web_trf loaded")
            except OSError:
                logger.warning("en_core_web_trf not found - falling back to en_core_web_sm")
                _nlp = spacy.load("en_core_web_sm")
        except Exception as exc:
            logger.warning("spaCy model unavailable, using regex fallback: %s", exc)
            _nlp = False
    return _nlp


class SpacyNERExtractor:
    def extract(self, text: str) -> list[dict]:
        nlp = _get_nlp()
        if not nlp:
            return self._regex_entities(text)

        doc = nlp((text or "")[:1000])
        seen = set()
        entities = []
        for ent in doc.ents:
            if ent.label_ in RELEVANT_LABELS and ent.text not in seen:
                seen.add(ent.text)
                entities.append(
                    {
                        "text": ent.text,
                        "label": ent.label_,
                        "start": ent.start_char,
                        "end": ent.end_char,
                    }
                )
        return entities

    def extract_relations(self, text: str, entities: list[dict]) -> list[dict]:
        nlp = _get_nlp()
        if not entities:
            return []
        if not nlp:
            names = [entity.get("text") for entity in entities if entity.get("text")][:2]
            if len(names) >= 2:
                return [
                    {
                        "subject": names[0],
                        "predicate": "related_to",
                        "object": names[1],
                        "confidence": 0.35,
                        "source_text": (text or "")[:200],
                    }
                ]
            return []

        doc = nlp((text or "")[:500])
        entity_texts = {entity["text"] for entity in entities}
        relations = []

        for sent in doc.sents:
            ents_in_sent = [token for token in sent if token.text in entity_texts]
            if len(ents_in_sent) < 2:
                continue
            verbs = [token for token in sent if token.pos_ == "VERB"]
            if verbs:
                relations.append(
                    {
                        "subject": ents_in_sent[0].text,
                        "predicate": verbs[0].lemma_,
                        "object": ents_in_sent[-1].text,
                        "confidence": 0.65,
                        "source_text": sent.text[:200],
                    }
                )
        return relations

    def _regex_entities(self, text: str) -> list[dict]:
        entities = []
        seen = set()
        for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text or ""):
            value = match.group(1)
            if value in seen or len(value) < 3:
                continue
            seen.add(value)
            entities.append(
                {
                    "text": value,
                    "label": "ORG",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        return entities[:20]


EntityExtractor = SpacyNERExtractor