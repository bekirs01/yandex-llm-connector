"""Service-advisor replies: answer first, one real next step, no invented shop."""

from __future__ import annotations

import json
from unittest import mock

import httpx

from webapp.chat_service import ChatService
from webapp.customer_voice import compose_reply
from webapp.grounding import ground_conversation
from webapp.reply_writer import WriterContext, check_reply, topic_service
from webapp.turn_reading import read_turn


OIL = "Mazda 6 2014, я в Казани. Что входит в стоимость замены масла?"
SHOP = {
    "workshop": "Север",
    "address": "Казань, улица Тестовая, 1",
    "phone": "+7 843 000-00-11",
    "hours": "ежедневно 9:00–20:00",
    "services": ["engine-oil-change", "throttle-cleaning-change", "disc-pad-rotor-change"],
    "prices": {
        "engine-oil-change": {
            "depends_on": "объём двигателя",
            "amounts": {"1.6": "3200 ₽", "2.0": "3900 ₽"},
            "includes": ["масло", "фильтр", "работа"],
        },
        "disc-pad-rotor-change": {
            "amount": "4500 ₽",
            "includes": ["колодки", "работа"],
        },
    },
}


def _reply(messages, facts=None):
    reading = read_turn(messages)
    grounded = ground_conversation(messages, reading)
    with mock.patch("webapp.customer_voice.verified_business", return_value=facts):
        text = compose_reply(messages, reading, None, None, grounded)
    return grounded, text


def test_oil_inclusion_explains_the_lines_and_offers_one_draft():
    _grounded, text = _reply([{"role": "user", "text": OIL}])
    folded = text.casefold()
    assert "масл" in folded and "фильтр" in folded and "работ" in folded
    assert "составлю" in folded
    assert "точной цены" not in folded
    assert "у нас" not in folded and "к нам" not in folded
    assert text.count("?") == 0


def test_yes_after_the_draft_offer_returns_the_message():
    offered = (
        "Смета на замену масла обычно состоит из масла, фильтра и работы. "
        "Если хотите, составлю сообщение с просьбой полной сметы."
    )
    messages = [
        {"role": "user", "text": OIL},
        {"role": "assistant", "text": offered},
        {"role": "user", "text": "да"},
    ]
    _grounded, text = _reply(messages)
    assert "«" in text and "»" in text
    assert "Mazda" in text and "Казан" in text
    assert "масл" in text.casefold()
    assert "запис" not in text.casefold()
    _grounded, again = _reply(messages[:-1] + [{"role": "user", "text": "давайте"}])
    assert "«" in again and "Mazda" in again


def test_yes_without_an_offer_is_not_a_booking():
    messages = [
        {"role": "user", "text": "Mazda 6 2014, я в Казани. Нужна замена масла."},
        {"role": "assistant", "text": "Замена масла на Mazda 6, 2014, Казань."},
        {"role": "user", "text": "да"},
    ]
    _grounded, text = _reply(messages)
    folded = text.casefold()
    assert "запис" in folded
    assert "не подтвержда" in folded
    assert "«" not in text


def test_address_offer_returns_only_the_verified_address():
    messages = [
        {"role": "user", "text": "Где вы находитесь?"},
        {"role": "assistant", "text": "Могу назвать адрес."},
        {"role": "user", "text": "хорошо"},
    ]
    _grounded, text = _reply(messages, SHOP)
    assert "улица Тестовая, 1" in text
    assert "запис" not in text.casefold()
    _grounded, missing = _reply(messages, None)
    assert "не называю" in missing.casefold()
    assert "Тестовая" not in missing


def test_idle_without_a_shop_does_not_invite_anyone_over():
    _grounded, text = _reply([{"role": "user", "text": "На холостых плавают обороты."}])
    folded = text.casefold()
    assert "оборот" in folded
    assert "причин" in folded
    assert "у нас" not in folded and "к нам" not in folded
    assert "составлю" in folded
    assert "точно" not in folded


def test_verified_shop_can_invite_and_a_catalog_match_cannot():
    text = _reply([{"role": "user", "text": "На холостых плавают обороты."}], SHOP)[1]
    folded = text.casefold()
    assert "подъехать к нам" in folded
    assert "улица тестовая, 1" in text.casefold()
    assert "не запись" in folded
    assert "сразу" in folded
    assert "записаны" not in folded
    oil_only = dict(SHOP, services=["engine-oil-change"], prices={})
    refused = _reply([{"role": "user", "text": "На холостых плавают обороты."}], oil_only)[1]
    assert "к нам" not in refused.casefold()


def test_verified_price_names_the_coverage_and_a_missing_detail_is_asked_once():
    asked = [{"role": "user", "text": "Skoda Octavia 2016. Сколько будет стоить замена дисковых колодок?"}]
    _grounded, text = _reply(asked, SHOP)
    assert "4500" in text
    assert "колодк" in text.casefold() and "работ" in text.casefold()
    assert text.count("?") == 0

    oil = [{"role": "user", "text": "Mazda 6 2014. Сколько будет стоить замена масла?"}]
    _grounded, question = _reply(oil, SHOP)
    assert "объём" in question.casefold() or "объем" in question.casefold()
    assert question.count("?") == 1
    assert "3200" not in question
    followed = oil + [
        {"role": "assistant", "text": question},
        {"role": "user", "text": "1.6"},
    ]
    _grounded, priced = _reply(followed, SHOP)
    assert "3200" in priced
    assert "масл" in priced.casefold()
    assert "запис" not in priced.casefold()


def test_verified_capability_ends_without_an_extra_offer():
    _grounded, text = _reply(
        [{"role": "user", "text": "Вы меняете масло в двигателе?"}],
        SHOP,
    )
    assert text.casefold().startswith("да")
    assert "масл" in text.casefold()
    assert "?" not in text
    assert "составлю" not in text.casefold()
    assert "подъехать" not in text.casefold()


def test_oil_change_after_idle_keeps_the_car_and_drops_the_symptom():
    messages = [
        {"role": "user", "text": "Mazda 6 2014, я в Казани. На холостых плавают обороты."},
        {"role": "assistant", "text": "На холостых плавают обороты. По переписке причину не назову."},
        {"role": "user", "text": "Теперь другое: нужна замена масла."},
    ]
    grounded, text = _reply(messages)
    folded = text.casefold()
    assert "переходим к замене масла" in folded
    assert "масл" in folded and "фильтр" in folded and "составлю" in folded
    assert "mazda" in folded
    assert "казан" in folded
    assert "плава" not in folded
    assert "оборот" not in folded
    assert grounded.city and "Казан" in grounded.city


def test_model_reply_must_answer_and_the_fallback_does():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract"})
    payload = {
        "request_id": "55555555-5555-4555-8555-555555555555",
        "conversation_id": "66666666-6666-4666-8666-666666666666",
        "messages": [{"role": "user", "text": OIL}],
    }

    def bad_post(url, json=None, timeout=None):
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "Точной цены здесь нет."}}],
            "usage": {"completion_tokens": 8},
        }
        return response

    with mock.patch("webapp.reply_writer.httpx.post", side_effect=bad_post), \
            mock.patch("webapp.chat_service._stored_reply", return_value=None), \
            mock.patch("webapp.chat_service._conversation_tasks", return_value=[]), \
            mock.patch("webapp.chat_service._record_visible_reply") as recorded:
        status, body = service.handle_chat(payload)
    assert status == 200
    assert body["metrics"]["response_origin"] == "fallback"
    text = body["message"]["text"]
    folded = text.casefold()
    assert "масл" in folded and "фильтр" in folded and "работ" in folded
    assert "составлю" in folded
    assert "точной цены" not in folded
    override = recorded.call_args.kwargs["service_override"]
    assert override[0] == "engine-oil-change"

    good = (
        "Смета на замену масла обычно состоит из масла, фильтра и работы. "
        "Какие строки подтверждены, отсюда не видно. "
        "Если хотите, составлю сообщение с просьбой полной сметы."
    )

    def good_post(url, json=None, timeout=None):
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": good}}],
            "usage": {"completion_tokens": 30},
        }
        return response

    with mock.patch("webapp.reply_writer.httpx.post", side_effect=good_post), \
            mock.patch("webapp.chat_service._stored_reply", return_value=None), \
            mock.patch("webapp.chat_service._conversation_tasks", return_value=[]), \
            mock.patch("webapp.chat_service._record_visible_reply"):
        status, body = service.handle_chat(payload)
    assert body["metrics"]["response_origin"] == "model"
    assert body["message"]["text"] == good


def test_acceptance_is_served_without_the_writer():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract"})
    payload = {
        "request_id": "77777777-7777-4777-8777-777777777777",
        "conversation_id": "88888888-8888-4888-8888-888888888888",
        "messages": [
            {"role": "user", "text": OIL},
            {"role": "assistant", "text": "Если хотите, составлю сообщение с просьбой полной сметы."},
            {"role": "user", "text": "да"},
        ],
    }
    with mock.patch("webapp.chat_service.write_reply", side_effect=AssertionError("writer")), \
            mock.patch("webapp.chat_service._stored_reply", return_value=None), \
            mock.patch("webapp.chat_service._record_visible_reply") as recorded:
        status, body = service.handle_chat(payload)
    assert status == 200
    text = body["message"]["text"]
    assert "«" in text and "Mazda" in text and "Казан" in text
    assert topic_service(payload["messages"]) == "engine-oil-change"
    assert recorded.called


def test_shop_voice_is_allowed_only_for_a_represented_workshop():
    plain = WriterContext(latest="на холостых плавают обороты", recent=[])
    invited = "Можете подъехать к нам на диагностику. Это не запись."
    assert check_reply(invited, plain) == "unsupported_claim:own_shop"
    allowed = WriterContext(latest="на холостых плавают обороты", recent=[], represents_shop=True)
    assert check_reply(invited, allowed) is None
    stale = WriterContext(
        latest="нужна замена масла",
        recent=[],
        dropped_symptom="на холостых плавают обороты",
    )
    assert check_reply("Плавают обороты, а масло тоже поменяем.", stale) == "unsupported_claim:old_topic"


def test_own_shop_phrase_stays_blocked_without_facts():
    ctx = WriterContext(latest="сколько стоит?", recent=[])
    assert check_reply("Приезжайте к нам, у нас это стоит недорого.", ctx).startswith("unsupported_claim")


def load_tests(loader, tests, pattern):
    import unittest
    suite = unittest.TestSuite()
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            suite.addTest(unittest.FunctionTestCase(func))
    return suite
