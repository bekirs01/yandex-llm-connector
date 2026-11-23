"""Offline scenarios for the dialogue policy. No model and no network."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from webapp.dialogue_policy import WITHHELD, plan_reply


ROOT = Path(__file__).resolve().parents[1]
BANNED = (
    "slots_after_message",
    "main_symptom",
    "known_service",
    "powertrain",
    "observed_context",
    "location_format",
    "search_area",
    "user_guess",
    "reported_conclusion",
    "hypothesis",
    "evidence",
    "unknown",
    "conflicting",
    "immobile",
    "json",
    "null",
    "{",
    "}",
    "руб",
    "₽",
    "неисправ",
    "записал вас",
    "свободно",
    "эвакуатор выехал",
)


def ev(
    slot: str,
    raw: str,
    interpretation: str,
    kind: str = "observation",
    message_id: str = "m1",
    supersedes: str | None = None,
    time_scope: str = "current",
) -> dict[str, object]:
    return {
        "slot": slot,
        "message_id": message_id,
        "raw_text": raw,
        "kind": kind,
        "time_scope": time_scope,
        "supersedes": supersedes,
        "interpretation": interpretation,
    }


def pack(slots: dict[str, str], evidence: list[dict[str, object]]) -> dict[str, object]:
    return {"slots_after_message": slots, "evidence": evidence}


def reasons(result) -> dict[str, str]:
    return {item.slot: item.reason for item in result.skipped_questions}


def assert_customer_shape(test: unittest.TestCase, result) -> None:
    text = result.customer_text
    test.assertTrue(text)
    test.assertLessEqual(text.count("?"), 1)
    folded = text.casefold()
    for token in BANNED:
        test.assertNotIn(token, folded)
        test.assertNotIn(token, text)
    test.assertNotIn("?", result.reply)
    if result.follow_up_question is None:
        test.assertNotIn("?", text)
        test.assertIsNone(result.follow_up_slot)
        test.assertEqual(result.reply, text)
    else:
        test.assertEqual(text.count("?"), 1)
        test.assertEqual(result.follow_up_question.count("?"), 1)
        test.assertTrue(text.endswith(result.follow_up_question))
        test.assertEqual(text, f"{result.reply} {result.follow_up_question}")
    test.assertEqual(result.withheld, WITHHELD)
    for item in result.acknowledged:
        test.assertNotIn(item.slot, text)


class DialoguePolicyTests(unittest.TestCase):
    def test_explicit_service_with_known_vehicle_and_powertrain_asks_nothing(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "engine-oil-change",
                "vehicle": "Toyota Camry 2018",
                "powertrain": "petrol",
            },
            [
                ev("intent", "поменяйте масло и фильтр", "known_service", "service_request"),
                ev("known_service", "поменяйте масло и фильтр", "engine-oil-change", "service_request"),
                ev("vehicle", "Toyota Camry 2018", "Toyota Camry 2018"),
                ev("powertrain", "бензин", "petrol"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(
            result.customer_text,
            "Принял: «поменяйте масло и фильтр», Toyota Camry 2018, бензин. "
            "Время и стоимость не подтверждаю.",
        )
        self.assertEqual(result.primary_situation, "explicit_service")
        self.assertIsNone(result.follow_up_question)
        skipped = reasons(result)
        self.assertEqual(skipped["vehicle"], "already_known")
        self.assertEqual(skipped["powertrain"], "already_known")
        self.assertEqual(skipped["event"], "irrelevant")
        self.assertEqual(skipped["location_format"], "irrelevant")
        self.assertEqual(skipped["search_area"], "irrelevant")
        service = next(item for item in result.acknowledged if item.slot == "known_service")
        self.assertEqual(service.grounding, "service_request")

    def test_explicit_service_asks_for_the_car_before_fuel_or_place(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "engine-oil-change",
            },
            [
                ev("intent", "поменяйте масло и фильтр", "known_service", "service_request"),
                ev("known_service", "поменяйте масло и фильтр", "engine-oil-change", "service_request"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.follow_up_slot, "vehicle")
        self.assertEqual(result.follow_up_reason, "missing_vehicle")
        self.assertEqual(
            result.customer_text,
            "Принял: «поменяйте масло и фильтр». Какая машина: марка, модель и примерно год?",
        )
        skipped = reasons(result)
        self.assertEqual(skipped["powertrain"], "deferred")
        self.assertEqual(skipped["event"], "irrelevant")
        self.assertEqual(skipped["search_area"], "irrelevant")
        self.assertEqual(skipped["location_format"], "irrelevant")

    def test_oil_change_asks_powertrain_only_after_the_car_is_known(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "engine-oil-change",
                "vehicle": "Toyota Camry 2018",
            },
            [
                ev("known_service", "поменяйте масло и фильтр", "engine-oil-change", "service_request"),
                ev("vehicle", "Toyota Camry 2018", "Toyota Camry 2018"),
                ev("intent", "поменяйте масло и фильтр", "known_service", "service_request"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.follow_up_slot, "powertrain")
        self.assertIn("Toyota Camry 2018", result.reply)
        self.assertNotIn("?", result.reply)
        skipped = reasons(result)
        self.assertEqual(skipped["vehicle"], "already_known")
        self.assertEqual(skipped["event"], "irrelevant")

    def test_brake_job_does_not_ask_powertrain_event_or_city(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "brake-pad-replacement",
                "vehicle": "Kia Rio 2017",
            },
            [
                ev("intent", "замените передние колодки", "known_service", "service_request"),
                ev("known_service", "замените передние колодки", "brake-pad-replacement", "service_request"),
                ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertIsNone(result.follow_up_question)
        self.assertEqual(
            result.customer_text,
            "Принял: «замените передние колодки», Kia Rio 2017. Время и стоимость не подтверждаю.",
        )
        skipped = reasons(result)
        self.assertEqual(skipped["powertrain"], "irrelevant")
        self.assertEqual(skipped["event"], "irrelevant")
        self.assertEqual(skipped["search_area"], "irrelevant")
        self.assertEqual(skipped["vehicle"], "already_known")

    def test_empty_extraction_asks_what_is_needed_and_invents_nothing(self) -> None:
        result = plan_reply(pack({}, []))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "unclear_request")
        self.assertEqual(result.follow_up_slot, "intent")
        self.assertFalse(result.uncertain)
        self.assertEqual(
            result.customer_text,
            "Пока не уловил суть. Что нужно: выполнить конкретную работу или разобраться, что случилось?",
        )
        self.assertEqual(reasons(result)["event"], "irrelevant")
        self.assertEqual(reasons(result)["vehicle"], "irrelevant")
        self.assertEqual(reasons(result)["search_area"], "irrelevant")

    def test_unclear_complaint_asks_only_what_is_happening(self) -> None:
        result = plan_reply(pack(
            {"intent": "complaint", "main_symptom": "unknown"},
            [ev("intent", "с машиной что-то не то", "complaint")],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "unclear_symptom")
        self.assertEqual(result.follow_up_slot, "main_symptom")
        self.assertEqual(result.follow_up_question, "Что именно происходит с машиной?")
        skipped = reasons(result)
        self.assertEqual(skipped["vehicle"], "deferred")
        self.assertEqual(skipped["event"], "irrelevant")
        self.assertEqual(skipped["location_format"], "irrelevant")
        self.assertEqual(skipped["search_area"], "irrelevant")
        self.assertEqual(text_questions(result), 1)

    def test_noise_asks_when_it_happens_not_the_event_or_the_city(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "стучит спереди",
                "vehicle": "Kia Rio 2017",
            },
            [
                ev("intent", "стучит спереди", "complaint"),
                ev("main_symptom", "стучит спереди", "стучит спереди"),
                ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.follow_up_slot, "observed_context")
        self.assertEqual(result.primary_situation, "complaint")
        self.assertIn("«стучит спереди»", result.reply)
        self.assertIn("Kia Rio 2017", result.reply)
        skipped = reasons(result)
        self.assertEqual(skipped["event"], "irrelevant")
        self.assertEqual(skipped["search_area"], "irrelevant")
        self.assertEqual(skipped["vehicle"], "already_known")
        self.assertEqual(skipped["location_format"], "irrelevant")

    def test_known_brake_context_does_not_ask_again_or_name_a_cause(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "скрипят колодки",
                "observed_context": "braking",
                "vehicle": "Kia Rio 2017",
            },
            [
                ev("main_symptom", "скрипят колодки", "скрипят колодки"),
                ev("observed_context", "при торможении", "braking"),
                ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
                ev("intent", "скрипят колодки", "complaint"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertIsNone(result.follow_up_question)
        self.assertIn("при торможении", result.customer_text)
        self.assertIn("Причину по описанию не ставлю.", result.customer_text)
        self.assertEqual(reasons(result)["observed_context"], "already_known")
        self.assertEqual(reasons(result)["event"], "irrelevant")

    def test_hypothesis_stays_an_assumption(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "стук",
                "previous_diagnosis": "user_guess",
                "vehicle": "Kia Rio 2017",
            },
            [
                ev("intent", "стук", "complaint"),
                ev("main_symptom", "стук", "стук"),
                ev("previous_diagnosis", "мне кажется, это стартер", "user_guess", "hypothesis"),
                ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "assumption")
        self.assertIn("предположение", result.customer_text)
        self.assertIn("«стук»", result.customer_text)
        self.assertIn("стартер", result.customer_text)
        self.assertIn("Kia Rio 2017", result.customer_text)
        self.assertIn("Догадку не подтверждаю", result.customer_text)
        guess = next(item for item in result.acknowledged if item.slot == "previous_diagnosis")
        self.assertEqual(guess.grounding, "assumption")
        fact = next(item for item in result.acknowledged if item.slot == "main_symptom")
        self.assertEqual(fact.grounding, "reported_fact")
        self.assertEqual(result.follow_up_slot, "observed_context")
        self.assertNotEqual(result.follow_up_slot, "previous_diagnosis")

    def test_reported_diagnosis_is_not_confirmed(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "external_conclusion",
                "main_symptom": "гул на скорости",
                "previous_diagnosis": "reported_conclusion",
                "observed_context": "moving",
                "vehicle": "Kia Rio 2016",
            },
            [
                ev("previous_diagnosis", "подшипник ступицы", "reported_conclusion", "reported_diagnosis"),
                ev("main_symptom", "гул на скорости", "гул на скорости"),
                ev("observed_context", "на скорости", "moving"),
                ev("vehicle", "Kia Rio 2016", "Kia Rio 2016"),
                ev("intent", "в сервисе сказали", "external_conclusion"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "reported_conclusion")
        self.assertIsNone(result.follow_up_question)
        self.assertIn("чужое заключение", result.customer_text)
        self.assertIn("«подшипник ступицы»", result.customer_text)
        self.assertIn("не подтверждаю", result.customer_text)
        self.assertIn("Kia Rio 2016", result.customer_text)
        claim = next(item for item in result.acknowledged if item.slot == "previous_diagnosis")
        self.assertEqual(claim.grounding, "reported_claim")
        self.assertEqual(reasons(result)["event"], "irrelevant")
        self.assertEqual(reasons(result)["search_area"], "irrelevant")

    def test_multi_turn_vehicle_correction_changes_the_car_and_the_opening(self) -> None:
        first_slots = {
            "intent": "complaint",
            "main_symptom": "не заводится",
            "vehicle": "Nissan Leaf 2019",
            "powertrain": "electric",
            "current_state": "immobile",
        }
        first = plan_reply(pack(
            first_slots,
            [
                ev("intent", "не заводится", "complaint"),
                ev("main_symptom", "не заводится", "не заводится"),
                ev("vehicle", "Nissan Leaf 2019", "Nissan Leaf 2019"),
                ev("powertrain", "электромобиль", "electric"),
                ev("current_state", "стоит во дворе", "immobile"),
            ],
        ))
        second_slots = {
            "intent": "complaint",
            "main_symptom": "не заводится",
            "vehicle": "Skoda Octavia 2016",
            "powertrain": "petrol",
            "current_state": "immobile",
        }
        second = plan_reply(
            pack(
                second_slots,
                [
                    ev(
                        "vehicle",
                        "это не Leaf, а Skoda Octavia 2016",
                        "Skoda Octavia 2016",
                        message_id="m2",
                        supersedes="m1",
                    ),
                    ev(
                        "powertrain",
                        "на бензине",
                        "petrol",
                        message_id="m2",
                        supersedes="m1",
                    ),
                ],
            ),
            prior_slots=first_slots,
            asked_slots=[first.follow_up_slot or ""],
        )
        assert_customer_shape(self, first)
        assert_customer_shape(self, second)
        self.assertEqual(first.follow_up_slot, "location_format")
        self.assertNotEqual(first.follow_up_slot, "vehicle")
        self.assertNotEqual(first.follow_up_slot, "event")
        self.assertTrue(first.customer_text.startswith("Понял, что сама машина сейчас не едет"))
        self.assertIn("Nissan Leaf 2019", first.customer_text)
        self.assertEqual(second.primary_situation, "correction")
        self.assertIsNone(second.follow_up_question)
        self.assertTrue(second.customer_text.startswith("Поправил по вашим словам:"))
        self.assertNotEqual(first.customer_text[:24], second.customer_text[:24])
        self.assertIn("не Nissan Leaf 2019, а Skoda Octavia 2016", second.customer_text)
        self.assertIn("теперь бензин, не электромобиль", second.customer_text)
        self.assertIn("«не заводится»", second.customer_text)
        self.assertEqual(reasons(second)["vehicle"], "already_known")
        self.assertEqual(reasons(second)["location_format"], "already_asked")
        self.assertEqual(reasons(second)["event"], "irrelevant")
        current = next(item for item in second.acknowledged if item.slot == "vehicle")
        self.assertEqual(current.value, "Skoda Octavia 2016")
        self.assertNotIn("Nissan Leaf 2019", current.value)

    def test_multi_turn_context_correction_drops_the_old_situation(self) -> None:
        prior = {
            "intent": "complaint",
            "main_symptom": "скрипят колодки",
            "observed_context": "braking",
            "vehicle": "Kia Rio 2017",
        }
        result = plan_reply(
            pack(
                {
                    "intent": "complaint",
                    "main_symptom": "скрипят колодки",
                    "observed_context": "moving",
                    "vehicle": "Kia Rio 2017",
                },
                [
                    ev(
                        "observed_context",
                        "не при торможении, а когда разгоняюсь",
                        "moving",
                        message_id="m2",
                        supersedes="m1",
                    ),
                ],
            ),
            prior_slots=prior,
        )
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "correction")
        self.assertIsNone(result.follow_up_question)
        self.assertIn("уже не при торможении, а на ходу", result.customer_text)
        self.assertIn("«скрипят колодки»", result.customer_text)
        self.assertNotIn("Причину по описанию не ставлю.", result.customer_text)
        context = next(item for item in result.acknowledged if item.slot == "observed_context")
        self.assertEqual(context.value, "moving")
        self.assertEqual(reasons(result)["observed_context"], "already_known")
        self.assertEqual(reasons(result)["event"], "irrelevant")

    def test_broken_shape_asks_for_a_rephrase_without_json(self) -> None:
        samples = [
            None,
            [],
            {"slots_after_message": ["vehicle"], "evidence": []},
            {"slots_after_message": {"vehicle": 2019}, "evidence": []},
            {"evidence": []},
        ]
        for sample in samples:
            result = plan_reply(sample)  # type: ignore[arg-type]
            assert_customer_shape(self, result)
            self.assertTrue(result.uncertain)
            self.assertEqual(result.primary_situation, "uncertain_output")
            self.assertEqual(result.follow_up_reason, "rephrase")
            self.assertIsNone(result.follow_up_slot)
            self.assertEqual(result.acknowledged, ())
            blob = json.dumps(sample, ensure_ascii=False, default=str)
            self.assertNotIn(blob, result.customer_text)
            self.assertNotIn("2019", result.customer_text)

    def test_mismatched_interpretation_is_not_spoken(self) -> None:
        result = plan_reply(pack(
            {"vehicle": "Toyota Camry 2018"},
            [ev("vehicle", "бмв", "BMW X5")],
        ))
        assert_customer_shape(self, result)
        self.assertTrue(result.uncertain)
        self.assertEqual(result.acknowledged, ())
        self.assertNotIn("Toyota", result.customer_text)
        self.assertNotIn("BMW", result.customer_text)
        self.assertNotIn("бмв", result.customer_text)
        self.assertEqual(result.follow_up_reason, "rephrase")
        self.assertTrue(any("does not match" in reason for reason in result.uncertainty_reasons))

    def test_partial_evidence_keeps_only_the_valid_fact(self) -> None:
        result = plan_reply(pack(
            {"vehicle": "Toyota Camry 2018", "main_symptom": "не заводится"},
            [
                ev("vehicle", "Camry 2018", "Toyota Camry 2018"),
                {"slot": "main_symptom", "raw_text": "SLOTDUMP"},
            ],
        ))
        assert_customer_shape(self, result)
        self.assertTrue(result.uncertain)
        self.assertEqual(result.primary_situation, "uncertain_output")
        self.assertIn("Toyota Camry 2018", result.customer_text)
        self.assertNotIn("SLOTDUMP", result.customer_text)
        self.assertNotIn("не заводится", result.customer_text)
        self.assertEqual(result.follow_up_reason, "rephrase")
        self.assertEqual(
            [item.slot for item in result.acknowledged],
            ["vehicle"],
        )

    def test_valid_request_survives_one_broken_evidence_item(self) -> None:
        result = plan_reply(pack(
            {"intent": "known_service", "known_service": "engine-oil-change"},
            [
                ev("intent", "поменяйте масло и фильтр", "known_service", "service_request"),
                ev("known_service", "поменяйте масло и фильтр", "engine-oil-change", "service_request"),
                {"raw_text": "SLOTDUMP"},
            ],
        ))
        assert_customer_shape(self, result)
        self.assertTrue(result.uncertain)
        self.assertEqual(result.primary_situation, "explicit_service")
        self.assertEqual(result.follow_up_slot, "vehicle")
        self.assertTrue(result.customer_text.startswith("Сообщение разобрано не полностью. Принял:"))
        self.assertIn("«поменяйте масло и фильтр»", result.customer_text)
        self.assertNotIn("SLOTDUMP", result.customer_text)

    def test_does_not_repeat_a_question_that_was_already_asked(self) -> None:
        payload = pack(
            {"intent": "complaint", "main_symptom": "unknown"},
            [ev("intent", "с машиной что-то не то", "complaint")],
        )
        again = plan_reply(payload, asked_slots=["main_symptom"])
        assert_customer_shape(self, again)
        self.assertEqual(again.follow_up_slot, "vehicle")
        self.assertEqual(again.primary_situation, "missing_detail")
        self.assertEqual(reasons(again)["main_symptom"], "already_asked")
        self.assertNotIn("Что именно происходит с машиной?", again.customer_text)
        self.assertTrue(again.customer_text.startswith("По жалобе переспрашивать не буду."))

        exhausted = plan_reply(payload, asked_slots=["main_symptom", "vehicle"])
        assert_customer_shape(self, exhausted)
        self.assertIsNone(exhausted.follow_up_question)
        self.assertEqual(exhausted.primary_situation, "questions_exhausted")
        self.assertEqual(exhausted.customer_text, "Пока не буду повторять те же вопросы.")
        self.assertEqual(reasons(exhausted)["main_symptom"], "already_asked")
        self.assertEqual(reasons(exhausted)["vehicle"], "already_asked")

    def test_known_water_event_asks_for_help_format_not_the_event(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "после лужи не заводится",
                "event": "water",
                "current_state": "immobile",
                "vehicle": "Skoda Octavia 2014",
                "powertrain": "petrol",
            },
            [
                ev("main_symptom", "после лужи не заводится", "после лужи не заводится"),
                ev("event", "после лужи", "water"),
                ev("current_state", "не заводится", "immobile"),
                ev("vehicle", "Skoda Octavia 2014", "Skoda Octavia 2014"),
                ev("powertrain", "бензин", "petrol"),
                ev("intent", "после лужи не заводится", "complaint"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "immobile")
        self.assertEqual(result.follow_up_slot, "location_format")
        self.assertIn("после воды", result.reply)
        self.assertIn("«после лужи не заводится»", result.reply)
        self.assertEqual(reasons(result)["event"], "already_known")
        self.assertEqual(reasons(result)["vehicle"], "already_known")
        self.assertNotIn("После чего это началось?", result.customer_text)

    def test_shop_search_asks_for_the_city_only_when_it_is_missing(self) -> None:
        missing = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "engine-oil-change",
                "vehicle": "Toyota Camry 2018",
                "powertrain": "petrol",
            },
            [
                ev("intent", "подберите сервис для замены масла", "known_service", "service_request"),
                ev("known_service", "подберите сервис для замены масла", "engine-oil-change", "service_request"),
                ev("vehicle", "Toyota Camry 2018", "Toyota Camry 2018"),
                ev("powertrain", "бензин", "petrol"),
            ],
        ))
        known = plan_reply(pack(
            {
                "intent": "known_service",
                "known_service": "engine-oil-change",
                "vehicle": "Toyota Camry 2018",
                "powertrain": "petrol",
                "location_format": "workshop",
                "search_area": "Казань",
            },
            [
                ev("known_service", "замена масла", "engine-oil-change", "service_request"),
                ev("vehicle", "Toyota Camry 2018", "Toyota Camry 2018"),
                ev("powertrain", "бензин", "petrol"),
                ev("location_format", "в сервис", "workshop"),
                ev("search_area", "Казань", "Казань"),
                ev("intent", "замена масла", "known_service", "service_request"),
            ],
        ))
        assert_customer_shape(self, missing)
        assert_customer_shape(self, known)
        self.assertEqual(missing.primary_situation, "shop_search")
        self.assertEqual(missing.follow_up_slot, "search_area")
        self.assertEqual(reasons(missing)["event"], "irrelevant")
        self.assertEqual(reasons(missing)["vehicle"], "already_known")
        self.assertEqual(reasons(missing)["location_format"], "irrelevant")
        self.assertIsNone(known.follow_up_question)
        self.assertIn("Казань", known.customer_text)
        self.assertIn("мастерскую, время и стоимость не называю", known.customer_text)
        self.assertNotIn("Автомир", known.customer_text)
        self.assertEqual(reasons(known)["search_area"], "already_known")

    def test_conflicting_vehicle_asks_which_one_is_right(self) -> None:
        result = plan_reply(pack(
            {"vehicle": "conflicting", "intent": "complaint"},
            [
                ev("vehicle", "то Camry, то Rio", "conflicting"),
                ev("intent", "то Camry, то Rio", "complaint"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "conflict")
        self.assertEqual(result.follow_up_slot, "vehicle")
        self.assertEqual(result.follow_up_reason, "conflict")
        self.assertEqual(result.follow_up_question, "Какая машина верная?")
        self.assertEqual(text_questions(result), 1)
        conflict = next(item for item in result.acknowledged if item.slot == "vehicle")
        self.assertEqual(conflict.grounding, "conflict")

    def test_disappeared_symptom_does_not_become_a_tow(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "вчера не заводилась, сегодня завелась",
                "current_state": "disappeared",
                "vehicle": "Toyota Camry 2015",
            },
            [
                ev(
                    "main_symptom",
                    "вчера не заводилась, сегодня завелась",
                    "вчера не заводилась, сегодня завелась",
                    time_scope="past",
                ),
                ev("current_state", "сегодня завелась", "disappeared", time_scope="current"),
                ev("vehicle", "Toyota Camry 2015", "Toyota Camry 2015"),
                ev("intent", "вчера не заводилась", "complaint"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "symptom_resolved")
        self.assertIsNone(result.follow_up_question)
        self.assertIn("сегодня завелась", result.customer_text)
        self.assertIn("выезд не предлагаю", result.customer_text)
        self.assertEqual(reasons(result)["location_format"], "irrelevant")
        self.assertEqual(reasons(result)["event"], "irrelevant")
        self.assertEqual(reasons(result)["powertrain"], "irrelevant")

    def test_several_topics_get_one_question(self) -> None:
        result = plan_reply(pack(
            {"intent": "multiple", "main_symptom": "multiple", "known_service": "ambiguous_candidates"},
            [
                ev("intent", "и стук, и масло", "multiple"),
                ev("main_symptom", "стук", "multiple"),
                ev("known_service", "поменяйте масло", "ambiguous_candidates", "service_request"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "several_topics")
        self.assertEqual(result.follow_up_slot, "intent")
        self.assertEqual(result.follow_up_question, "С чего удобнее начать?")
        self.assertEqual(text_questions(result), 1)
        self.assertIn("«и стук, и масло»", result.customer_text)
        self.assertEqual(reasons(result)["main_symptom"], "deferred")

    def test_unnamed_trigger_is_asked_only_when_nothing_more_useful_is_open(self) -> None:
        result = plan_reply(pack(
            {
                "intent": "complaint",
                "main_symptom": "стучит после этого",
                "observed_context": "moving",
                "vehicle": "Kia Rio 2017",
                "powertrain": "petrol",
            },
            [
                ev("main_symptom", "стучит после этого", "стучит после этого"),
                ev("observed_context", "на ходу", "moving"),
                ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
                ev("powertrain", "бензин", "petrol"),
                ev("intent", "стучит после этого", "complaint"),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.follow_up_slot, "event")
        self.assertEqual(result.follow_up_reason, "unnamed_event")
        self.assertIn("на ходу", result.reply)
        self.assertEqual(reasons(result)["observed_context"], "already_known")

    def test_key_request_does_not_ask_for_documents(self) -> None:
        result = plan_reply(pack(
            {"intent": "known_service", "known_service": "lockout"},
            [
                ev("intent", "нужно вскрыть машину, ключ потерял", "known_service", "service_request"),
                ev(
                    "known_service",
                    "нужно вскрыть машину, ключ потерял",
                    "lockout",
                    "service_request",
                ),
            ],
        ))
        assert_customer_shape(self, result)
        self.assertIn("Право доступа проверит мастерская", result.reply)
        self.assertIn("документы здесь не спрашиваю", result.reply)
        self.assertEqual(result.follow_up_slot, "vehicle")
        self.assertNotIn("паспорт", result.customer_text)
        self.assertNotIn("пришлите", result.customer_text)

    def test_empty_evidence_keeps_accumulated_facts_and_asks_nothing(self) -> None:
        result = plan_reply(pack(
            {
                "vehicle": "Nissan Leaf 2019",
                "main_symptom": "не заводится",
                "powertrain": "electric",
            },
            [],
        ))
        assert_customer_shape(self, result)
        self.assertEqual(result.primary_situation, "no_new_facts")
        self.assertIsNone(result.follow_up_question)
        self.assertFalse(result.uncertain)
        self.assertIn("Nissan Leaf 2019", result.customer_text)
        self.assertIn("«не заводится»", result.customer_text)
        self.assertTrue(result.customer_text.startswith("Новых сведений не вижу."))

    def test_openings_are_not_one_repeated_template(self) -> None:
        samples = [
            plan_reply(pack(
                {
                    "intent": "known_service",
                    "known_service": "engine-oil-change",
                    "vehicle": "Toyota Camry 2018",
                    "powertrain": "petrol",
                },
                [
                    ev("known_service", "поменяйте масло и фильтр", "engine-oil-change", "service_request"),
                    ev("vehicle", "Toyota Camry 2018", "Toyota Camry 2018"),
                    ev("powertrain", "бензин", "petrol"),
                    ev("intent", "поменяйте масло", "known_service", "service_request"),
                ],
            )),
            plan_reply(pack({}, [])),
            plan_reply(pack(
                {"intent": "complaint", "main_symptom": "unknown"},
                [ev("intent", "с машиной что-то не то", "complaint")],
            )),
            plan_reply(pack(
                {"intent": "complaint", "main_symptom": "стучит спереди", "vehicle": "Kia Rio 2017"},
                [
                    ev("main_symptom", "стучит спереди", "стучит спереди"),
                    ev("vehicle", "Kia Rio 2017", "Kia Rio 2017"),
                    ev("intent", "стучит спереди", "complaint"),
                ],
            )),
            plan_reply(pack(
                {"vehicle": "conflicting"},
                [ev("vehicle", "то одна, то другая", "conflicting")],
            )),
            plan_reply(None),
        ]
        openings = [sample.customer_text.split(".", 1)[0] for sample in samples]
        self.assertEqual(len(openings), len(set(openings)))
        for sample in samples:
            assert_customer_shape(self, sample)

    def test_module_stays_standalone_and_has_no_turkish_letters(self) -> None:
        source = (ROOT / "webapp" / "dialogue_policy.py").read_text(encoding="utf-8")
        test_source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("chat_service", source)
        self.assertNotIn("local_models", source)
        self.assertNotIn("httpx", source)
        forbidden = "\u00e7\u011f\u0131\u00f6\u015f\u00fc\u00c7\u011e\u0130\u00d6\u015e\u00dc"
        for text in (source, test_source):
            for letter in forbidden:
                self.assertNotIn(letter, text)


def text_questions(result) -> int:
    return result.customer_text.count("?")


if __name__ == "__main__":
    unittest.main()
