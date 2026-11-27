from unittest import mock

import httpx

from webapp.chat_service import ChatService
from webapp.reply_writer import (
    WriterContext,
    check_reply,
    pending_action,
    plan_turn,
    write_reply,
)

OIL = ("engine-oil-change", "Замена моторного масла и масляного фильтра")
SMOKE = ("intake-smoke-test", "Проверка герметичности впуска дымогенератором")


def test_pending_action_reads_only_a_real_offer_or_question():
    offer = [{"role": "user", "text": "x"},
             {"role": "assistant", "text": "Под это подходит диагностика. Если хотите, составлю сообщение для сервиса."},
             {"role": "user", "text": "да"}]
    plain = [{"role": "user", "text": "x"},
             {"role": "assistant", "text": "Я не могу назвать цену."},
             {"role": "user", "text": "да"}]
    assert pending_action(offer).startswith("Если хотите, составлю")
    assert pending_action(plain) == ""


def test_bare_yes_without_an_offer_is_not_consent():
    ctx = plan_turn(WriterContext(latest="да", recent=[], current_task=SMOKE), short_reply=True)
    assert "неясно" in ctx.turn_note
    assert ctx.current_task == SMOKE


def test_new_service_switches_topic_and_keeps_the_old_one_for_later():
    ctx = WriterContext(latest="Вы меняете масло в двигателе?",
                        recent=[{"role": "user", "text": "подсос воздуха"}],
                        candidates=[OIL], current_task=SMOKE, customer_need="подсос")
    ctx = plan_turn(ctx, short_reply=False)
    assert ctx.current_task is None and ctx.recent == [] and ctx.customer_need == ""
    assert SMOKE in ctx.earlier_tasks


def test_mixed_request_goes_to_review():
    ctx = plan_turn(WriterContext(
        latest="Нужно поменять тормозные колодки и ещё ремень ГРМ", recent=[]), short_reply=False)
    assert len(ctx.mixed) == 2


def test_claim_check_is_independent_of_wording():
    ctx = WriterContext(latest="сколько стоит?", recent=[])
    assert check_reply("Замена масла стоит 2500 руб.", ctx) == "unsupported_claim:price"
    assert check_reply("Хорошо, запишем вас на завтра.", ctx) == "unsupported_claim:booking"
    assert check_reply("Проверка впуска уже проведена.", ctx) == "unsupported_claim:completed_work"
    assert check_reply("Точную цену назовёт сервис.", ctx) is None


def test_timeout_is_reported_as_fallback():
    with mock.patch("webapp.reply_writer.httpx.post", side_effect=httpx.ReadTimeout("slow")):
        result = write_reply(WriterContext(latest="x", recent=[]))
    assert result.origin == "fallback" and result.reason == "timeout" and result.text is None


def test_chat_marks_fallback_text_as_not_model_generated():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract"})
    payload = {
        "request_id": "33333333-3333-4333-8333-333333333333",
        "conversation_id": "44444444-4444-4444-8444-444444444444",
        "messages": [{"role": "user", "text": "Toyota Corolla 2015, нужна замена масла, сколько стоит?"}],
    }
    with mock.patch("webapp.reply_writer.httpx.post", side_effect=httpx.ReadTimeout("slow")), \
            mock.patch("webapp.chat_service._stored_reply", return_value=None), \
            mock.patch("webapp.chat_service._conversation_tasks", return_value=[]), \
            mock.patch("webapp.chat_service._record_visible_reply"):
        status, body = service.handle_chat(payload)
    assert status == 200
    assert body["metrics"]["response_origin"] == "fallback"
    assert body["metrics"]["fallback_reason"] == "timeout"
    assert body["model"] is None
    assert body["message"]["text"].strip()
