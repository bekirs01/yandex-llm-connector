"""The turn reader distinguishes social talk from requests that need facts."""

import unittest

from webapp.customer_voice import compose_reply
from webapp.dialogue_policy import plan_reply
from webapp.retrieval import rank_services
from webapp.turn_reading import read_turn


def _user(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "text": text}]


class TurnReadingTests(unittest.TestCase):
    def test_plain_thanks_is_social_and_price_follow_up_is_not(self) -> None:
        thanks = read_turn(_user("спасибо"))
        price = read_turn([
            {"role": "user", "text": "Нужно поменять масло на солярисе"},
            {"role": "assistant", "text": "Понял вас: замена масла."},
            {"role": "user", "text": "Спасибо, а сколько это стоит?"},
        ])
        self.assertTrue(thanks.social_only)
        self.assertFalse(thanks.needs_extraction)
        self.assertFalse(thanks.needs_retrieval)
        self.assertTrue(price.asks_price)
        self.assertFalse(price.social_only)
        self.assertFalse(price.needs_extraction)
        self.assertTrue(price.needs_retrieval)

    def test_greeting_with_a_question_is_not_only_a_greeting(self) -> None:
        text = "Привет, сколько стоит замена колодок на камри 2015 и когда можно приехать?"
        reading = read_turn(_user(text))
        self.assertTrue(reading.greeting)
        self.assertTrue(reading.asks_price)
        self.assertTrue(reading.asks_availability)
        self.assertTrue(reading.needs_extraction)
        reply = compose_reply(_user(text), reading, None, None)
        self.assertIn("Здравствуйте", reply)
        self.assertIn("цен", reply.casefold())
        self.assertNotRegex(reply.casefold(), r"\d+\s*(?:₽|руб)")
        self.assertIn("не подтверждаю", reply)
        self.assertNotIn("марку, модель и год", reply)
        self.assertIn("2015", reply)

    def test_slang_and_typos_stay_conversational(self) -> None:
        for text in ("здарова", "привт", "спс", "пасибки", "как дела?"):
            reading = read_turn(_user(text))
            self.assertTrue(reading.social_only, text)
            reply = compose_reply(_user(text), reading, None, None)
            self.assertNotIn("марку, модель", reply)
            self.assertLessEqual(reply.count("?"), 1)

    def test_short_answer_to_an_open_question_still_extracts(self) -> None:
        reading = read_turn([
            {"role": "user", "text": "Стучит спереди"},
            {"role": "assistant", "text": "В каком городе искать?"},
            {"role": "user", "text": "Казань"},
        ])
        self.assertTrue(reading.needs_extraction)
        self.assertTrue(reading.answers_open_question)

    def test_catalog_rank_uses_distinctive_words_only(self) -> None:
        catalog = [
            {"service_id": "oil", "source_title": "Замена моторного масла.", "aliases": ["поменять масло"]},
            {"service_id": "pads", "source_title": "Замена тормозных колодок.", "aliases": ["поменять колодки"]},
            {"service_id": "plugs", "source_title": "Замена свечей зажигания.", "aliases": ["поменять свечи"]},
        ]
        ranked = rank_services(catalog, "сколько стоит замена колодок")
        self.assertEqual(ranked[0].service_id, "pads")
        oil = rank_services(catalog, "Нужно поменять масло. Спасибо, а сколько это стоит?")
        self.assertEqual(oil[0].service_id, "oil")
        cold = rank_services(
            catalog + [{
                "service_id": "fridge",
                "source_title": "Обслуживание холодильной установки фургона.",
                "aliases": ["холодильник"],
            }],
            "Печка дует холодным",
        )
        self.assertFalse(any(item.service_id == "fridge" for item in cold))

    def test_plain_thanks_does_not_turn_into_a_greeting(self) -> None:
        reading = read_turn(_user("спасибо"))
        reply = compose_reply(_user("спасибо"), reading, None, None)
        self.assertEqual(reply, "Пожалуйста.")
        self.assertFalse(reading.greeting)

    def test_correction_reply_keeps_the_complaint_and_drops_the_repeated_context_question(self) -> None:
        extraction = {
            "slots_after_message": {
                "main_symptom": "Двигатель расходует масло и постукивает.; Двигатель расходует масло, стук слышен постоянно, громче на холодную.",
                "search_area": "Великий Новгород",
                "vehicle": "Volvo XC60, 2016",
            },
            "evidence": [
                {
                    "slot": "search_area",
                    "message_id": "m7",
                    "raw_text": "Великий Новгород",
                    "kind": "observation",
                    "time_scope": "current",
                    "supersedes": "m1",
                    "interpretation": "Великий Новгород",
                },
                {
                    "slot": "main_symptom",
                    "message_id": "m7",
                    "raw_text": "Двигатель расходует масло, стук слышен постоянно, громче на холодную",
                    "kind": "observation",
                    "time_scope": "current",
                    "supersedes": None,
                    "interpretation": "Двигатель расходует масло и постукивает.; Двигатель расходует масло, стук слышен постоянно, громче на холодную.",
                },
            ],
        }
        policy = plan_reply(
            extraction,
            prior_slots={
                "search_area": "Псков",
                "main_symptom": "Двигатель расходует масло и постукивает.",
            },
        )
        messages = [
            {"role": "user", "text": "Ищу сервис в Пскове, машина Вольво XC60 2016, дизель. Масло подъедает и постукивает."},
            {"role": "assistant", "text": "Уточню: постукивание слышно на холодную, на горячую или постоянно?"},
            {"role": "user", "text": "Постоянно, но громче на холодную."},
            {"role": "assistant", "text": "Хорошо."},
            {"role": "user", "text": "Стоп, я ошибся с городом — мне нужен не Псков, а Великий Новгород."},
        ]
        reply = compose_reply(messages, read_turn(messages), policy, None)
        folded = reply.casefold()
        self.assertIn("великий новгород", folded)
        self.assertTrue("холодн" in folded or "постук" in folded or "масл" in folded)
        self.assertNotIn("при торможении, на ходу, при повороте или на месте", folded)
        self.assertNotIn("сведение", folded)
        self.assertNotIn(";", reply)
