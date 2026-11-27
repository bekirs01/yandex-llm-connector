"""Customer facts stay inside the conversation that stated them."""

import unittest
from unittest import mock

from webapp.chat_service import ChatService
from webapp.customer_voice import compose_reply
from webapp.grounding import apply_extractor_facts, ground_conversation
from webapp.retrieval import RetrievalResult, RetrievedService, _catalog, confident_service, rank_services
from webapp.turn_reading import read_turn


def _turn(messages):
    reading = read_turn(messages)
    grounded = ground_conversation(messages, reading)
    return reading, grounded, compose_reply(messages, reading, None, None, grounded)


class GroundingTests(unittest.TestCase):
    def test_correction_replaces_only_the_model_and_keeps_the_year(self) -> None:
        messages = [
            {"role": "user", "text": "камри 2015, жрет масло"},
            {"role": "assistant", "text": "Расход масла на Camry 2015 принял."},
            {"role": "user", "text": "ой не камри, королла, год тот же"},
        ]
        _reading, grounded, reply = _turn(messages)
        self.assertEqual(grounded.model, "Corolla")
        self.assertEqual(grounded.year, "2015")
        self.assertTrue(grounded.skip_model)
        folded = reply.casefold()
        self.assertIn("corolla", folded)
        self.assertIn("2015", reply)
        self.assertNotIn("camry", folded)
        self.assertNotIn("сведение", folded)
        self.assertLessEqual(reply.count("?"), 1)

    def test_paraphrased_correction_uses_the_same_rule(self) -> None:
        messages = [
            {"role": "user", "text": "у меня камри, 2015 год, масло уходит"},
            {"role": "assistant", "text": "Понял."},
            {"role": "user", "text": "не Camry, а Corolla, год не менялся"},
        ]
        _reading, grounded, reply = _turn(messages)
        self.assertEqual(grounded.model, "Corolla")
        self.assertEqual(grounded.year, "2015")
        self.assertIn("2015", reply)
        self.assertIn("Corolla", reply)

    def test_misspelled_make_keeps_the_year_and_does_not_invent_a_model(self) -> None:
        messages = [{"role": "user", "text": "volswoogen и 2020 год"}]
        _reading, grounded, reply = _turn(messages)
        self.assertEqual(grounded.year, "2020")
        self.assertIsNone(grounded.model)
        self.assertNotIn("Golf", reply)
        self.assertNotIn("Tiguan", reply)
        self.assertNotIn("Passat", reply)
        self.assertLessEqual(reply.count("?"), 1)
        if grounded.make == "Volkswagen":
            self.assertIn("Volkswagen", reply)
        else:
            self.assertIn("2020", reply)
            self.assertIn("?", reply)

    def test_unclear_pronoun_asks_what_stopped(self) -> None:
        messages = [{"role": "user", "text": "он уже не работает"}]
        _reading, grounded, reply = _turn(messages)
        self.assertTrue(grounded.unclear_referent)
        self.assertTrue(grounded.skip_model)
        self.assertIn("Что именно", reply)
        self.assertNotIn("стартер", reply.casefold())

    def test_starter_turns_is_not_a_starter_repair(self) -> None:
        catalog = [
            {"service_id": "starter-repair", "source_title": "Диагностика, ремонт или замена стартера.", "aliases": ["замена стартера"]},
            {"service_id": "pads", "source_title": "Замена тормозных колодок.", "aliases": ["поменять колодки"]},
        ]
        self.assertEqual(rank_services(catalog, "Стартер крутит"), ())
        messages = [{"role": "user", "text": "Стартер крутит"}]
        _reading, grounded, reply = _turn(messages)
        self.assertFalse(grounded.should_retrieve)
        self.assertNotIn("замена стартера", reply.casefold())
        self.assertLessEqual(reply.count("?"), 1)

    def test_sunday_hours_do_not_become_a_tire_job(self) -> None:
        catalog = [
            {
                "service_id": "runflat-lowprofile-service",
                "source_title": "Работа с шинами Run Flat и низкопрофильными шинами.",
                "aliases": ["нужна услуга: работа с шинами Run Flat"],
            },
            {"service_id": "tire-fitting", "source_title": "Снятие и установка шин на диски.", "aliases": ["шиномонтаж"]},
        ]
        text = "я не про ремонт, я про то, работаете ли вы в воскресенье"
        self.assertEqual(rank_services(catalog, text), ())
        messages = [{"role": "user", "text": text}]
        reading, grounded, reply = _turn(messages)
        self.assertTrue(reading.asks_hours)
        self.assertFalse(grounded.should_retrieve)
        self.assertFalse(reading.needs_extraction)
        folded = reply.casefold()
        self.assertIn("воскрес", folded)
        self.assertNotIn("шин", folded)
        self.assertNotRegex(reply, r"\d{1,2}:\d{2}")

    def test_contrast_is_not_a_correction_and_a_price_question_keeps_the_job(self) -> None:
        knock = [{"role": "user", "text": "при торможении стучит, не когда просто качусь"}]
        reading = read_turn(knock)
        grounded = ground_conversation(knock, reading)
        reply = compose_reply(knock, reading, None, None, grounded)
        self.assertFalse(grounded.correction)
        self.assertNotIn("поправку", reply.casefold())
        self.assertIn("тормож", reply.casefold())

        price = [{"role": "user", "text": "добрый день, масло и фильтры по деньгам как выходят?"}]
        price_reading = read_turn(price)
        priced = ground_conversation(price, price_reading)
        price_reply = compose_reply(price, price_reading, None, None, priced)
        self.assertTrue(price_reading.asks_price)
        self.assertTrue(priced.skip_model)
        self.assertIn("масл", (priced.service or "").casefold())
        self.assertIn("цен", price_reply.casefold())
        self.assertNotIn("что случилось", price_reply.casefold())

    def test_advice_question_is_not_echoed_and_a_time_stays_on_booking(self) -> None:
        asked = [{"role": "user", "text": "если лампа чек горит, сразу ехать?"}]
        reading = read_turn(asked)
        grounded = ground_conversation(asked, reading)
        reply = compose_reply(asked, reading, None, None, grounded)
        self.assertTrue(grounded.asks_advice)
        self.assertTrue(grounded.skip_model)
        self.assertNotIn("сразу ехать", reply.casefold())
        self.assertIn("не скажу", reply.casefold())
        self.assertEqual(reply.count("?"), 1)

        booking = [
            {"role": "user", "text": "можно на субботу утром записаться?"},
            {"role": "assistant", "text": "Свободное окно отсюда не видно, поэтому запись не подтверждаю."},
            {"role": "user", "text": "тогда ближе к полудню, часов на одиннадцать"},
        ]
        follow = read_turn(booking)
        reply = compose_reply(booking, follow, None, None)
        self.assertTrue(follow.asks_booking)
        self.assertIn("время услышал", reply.casefold())
        self.assertNotIn("конкретнее", reply.casefold())

    def test_front_pads_do_not_match_the_word_before(self) -> None:
        catalog = [
            {"service_id": "prepurchase-inspection", "source_title": "Проверка автомобиля перед покупкой.", "aliases": []},
            {"service_id": "gear-selector-repair", "source_title": "Ремонт механизма выбора передач и кулисы.", "aliases": []},
            {"service_id": "disc-pad-rotor-change", "source_title": "Замена дисковых тормозных колодок и дисков.", "aliases": []},
        ]
        ranked = [item.service_id for item in rank_services(catalog, "сколько стоит замена передних колодок")]
        self.assertEqual(ranked, ["disc-pad-rotor-change"])

    def test_turbo_removal_does_not_rank_a_prepurchase_inspection_first(self) -> None:
        catalog = [
            {"service_id": "prepurchase-inspection", "source_title": "Проверка автомобиля перед покупкой.", "aliases": ["нужна проверка автомобиля перед покупкой"]},
            {"service_id": "turbo-actuator-repair", "source_title": "Ремонт привода управления турбиной.", "aliases": ["нужен ремонт привода управления турбиной"]},
            {"service_id": "vehicle-pickup-delivery", "source_title": "Доставка автомобиля в сервис и обратно.", "aliases": []},
        ]
        query = "Хочу снять турбину и поставить обратно — планирую отдать её на переборку отдельно."
        ranked = [item.service_id for item in rank_services(catalog, query)]
        self.assertNotIn("prepurchase-inspection", ranked[:1])
        self.assertNotIn("vehicle-pickup-delivery", ranked)

    def test_degraded_extraction_keeps_the_customer_fact(self) -> None:
        service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
        response = mock.Mock()
        response.status_code = 502
        response.json.return_value = {"error": "invalid model output", "details": ["raw_text"]}
        payload = {
            "request_id": "11111111-1111-4111-8111-111111111111",
            "conversation_id": "22222222-2222-4222-8222-222222222222",
            "messages": [{"role": "user", "text": "греется сильно, стрелка в красной зоне, рио 2017"}],
        }
        with mock.patch("webapp.chat_service.httpx.post", return_value=response), \
                mock.patch("webapp.chat_service._stored_reply", return_value=None):
            status, body = service.handle_chat(payload)
        self.assertEqual(status, 200)
        # The first urgent warning is fixed text and does not wait on a failing extractor.
        self.assertEqual(body["metrics"]["response_origin"], "grounded")
        self.assertEqual(body["model"], "Local conversation")
        self.assertNotIn("structured", body)
        self.assertTrue(body["message"]["text"].casefold().startswith("остановитесь"))
        self.assertIn("2017", body["message"]["text"])
        self.assertIn("Rio", body["message"]["text"])
        self.assertNotIn("complaint", body["message"]["text"].casefold())

    def test_stated_vehicle_answers_price_booking_and_equipment(self) -> None:
        price = [{"role": "user", "text": "Сколько стоит проверка впуска дымогенератором на Honda Civic 2009 и когда ближайшая запись?"}]
        _reading, grounded, reply = _turn(price)
        self.assertEqual(grounded.stated_vehicle, "Honda Civic")
        self.assertEqual(grounded.year, "2009")
        self.assertIn("цен", reply.split(".")[0].casefold())
        self.assertIn("не подтверждаю", reply.casefold())
        self.assertNotIn("какую машину", reply.casefold())
        self.assertNotIn("какая машина", reply.casefold())
        self.assertLessEqual(reply.count("?"), 1)

        follow = price + [
            {"role": "assistant", "text": reply},
            {"role": "user", "text": "Я в Саратове. А дымогенератор у вас точно есть?"},
        ]
        reading, grounded = read_turn(follow), ground_conversation(follow, read_turn(follow))
        self.assertEqual(grounded.city, "Саратове")
        self.assertEqual(grounded.stated_vehicle, "Honda Civic")
        self.assertEqual(grounded.year, "2009")
        self.assertTrue(grounded.asks_equipment)
        self.assertTrue(grounded.skip_model)
        found = RetrievalResult(
            (RetrievedService("intake-smoke-test", "Проверка герметичности впуска дымогенератором", 4),),
            (), 0, 0, "test", 0.0,
        )
        reply = compose_reply(follow, reading, None, found, grounded)
        folded = reply.casefold()
        self.assertIn("наличи", folded)
        self.assertIn("дымогенератор", folded)
        self.assertIn("каталоге", folded)
        self.assertIn("проверк", folded)
        self.assertIn("в саратове", folded)
        self.assertNotIn("герметичности", folded)
        self.assertNotIn("речь о таком заказе", folded)
        self.assertNotIn("civic", folded)
        self.assertNotRegex(reply, r"Саратове\s*\.?$")
        self.assertNotIn("цен", folded)
        self.assertNotIn("запись не подтверждаю", folded)
        self.assertEqual(reply.count("?"), 0)
        self.assertTrue(folded.startswith("дымогенератор"))

        other = [{"role": "user", "text": "Сколько стоит замена ремня ГРМ на Mazda 6 2014 и когда ближайшая запись?"}]
        _reading, grounded, reply = _turn(other)
        self.assertEqual(grounded.stated_vehicle, "Mazda 6")
        self.assertEqual(grounded.year, "2014")
        self.assertIn("цен", reply.split(".")[0].casefold())
        self.assertIn("не подтверждаю", reply.casefold())
        self.assertNotIn("какую машину", reply.casefold())

    def test_replacement_does_not_keep_the_old_year_or_city(self) -> None:
        messages = [
            {"role": "user", "text": "Нужна выездная диагностика, машина Kia Rio 2018 в Казани"},
            {"role": "assistant", "text": "Понял."},
            {"role": "user", "text": "Нет, это не Kia Rio, а Hyundai Solaris, и я в Москве"},
        ]
        reading, grounded, reply = _turn(messages)
        self.assertEqual(grounded.model, "Solaris")
        self.assertEqual(grounded.make, "Hyundai")
        self.assertIsNone(grounded.year)
        self.assertEqual(grounded.city, "Москва")
        self.assertNotIn("казан", (grounded.service or "").casefold())
        folded = reply.casefold()
        self.assertIn("solaris", folded)
        self.assertIn("москв", folded)
        self.assertNotIn("казан", folded)
        self.assertNotIn("2018", reply)
        self.assertNotIn("rio", folded)

        stale = {
            "slots_after_message": {"vehicle": "Kia Rio, 2018", "search_area": "Казань"},
            "evidence": [],
        }
        merged = apply_extractor_facts(grounded, stale, messages)
        self.assertEqual(merged.model, "Solaris")
        self.assertIsNone(merged.year)
        self.assertEqual(merged.city, "Москва")
        kept = compose_reply(messages, reading, None, None, merged)
        self.assertNotIn("казан", kept.casefold())
        self.assertNotIn("2018", kept)

    def test_urgent_guidance_leads_and_a_symptom_is_a_sentence(self) -> None:
        fuel = [{"role": "user", "text": "Залил в бак не то топливо, машина заглохла и больше не заводится. Что делать сейчас?"}]
        _reading, grounded, reply = _turn(fuel)
        self.assertEqual(grounded.urgent, "misfuel")
        self.assertTrue(reply.casefold().startswith("не заводите"))
        self.assertNotIn("что ещё происходит", reply.casefold())
        self.assertEqual(reply.count("?"), 0)

        knock = [{"role": "user", "text": "у Toyota Camry 2015 стучит подвеска слева"}]
        _reading, grounded, reply = _turn(knock)
        self.assertIn("Camry", reply)
        self.assertNotIn("у стучит", reply.casefold())

    def test_deterministic_extractor_slots_fill_only_supported_facts(self) -> None:
        """Slots are a fixed payload, not a live model call."""

        service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
        prediction = {
            "slots_after_message": {"vehicle": "Subaru Forester, 2016"},
            "evidence": [],
        }
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = prediction
        payload = {
            "request_id": "11111111-1111-4111-8111-111111111111",
            "conversation_id": "22222222-2222-4222-8222-222222222222",
            "messages": [{"role": "user", "text": "У меня Subaru Forester"}],
        }
        with mock.patch("webapp.chat_service.httpx.post", return_value=response):
            status, body = service.handle_chat(payload)
        self.assertEqual(status, 200)
        text = body["message"]["text"]
        self.assertIn("Subaru Forester", text)
        self.assertNotIn("2016", text)
        self.assertNotIn("какую машину", text.casefold())
        self.assertNotIn("какая машина", text.casefold())

    def test_paraphrase_stays_general_and_endoscopy_is_a_named_job(self) -> None:
        catalog = _catalog()
        paraphrase = "хочу проверить, не тянет ли воздух во впуске"
        ranked = rank_services(catalog, paraphrase, limit=3)
        ids = [item.service_id for item in ranked]
        self.assertIn("intake-smoke-test", ids)
        retrieved = RetrievalResult(tuple(ranked), (), 0, 0, "local-postgres", 0.0)
        self.assertIsNone(confident_service(retrieved))
        messages = [{"role": "user", "text": paraphrase}]
        reading, grounded = read_turn(messages), ground_conversation(messages, read_turn(messages))
        reply = compose_reply(messages, reading, None, retrieved, grounded)
        folded = reply.casefold()
        self.assertTrue("впуск" in folded or "воздух" in folded)
        self.assertIn("машину", folded)
        self.assertNotIn("дымогенератор", folded)
        self.assertNotIn("цен", folded)
        self.assertNotIn("охлаждающ", folded)
        self.assertLessEqual(reply.count("?"), 1)
        self.assertTrue(grounded.skip_model)

        endoscopy = "нужна эндоскопия цилиндров"
        named = rank_services(catalog, endoscopy, limit=3)
        self.assertTrue(named)
        self.assertEqual(named[0].service_id, "cylinder-endoscopy")
        found = RetrievalResult(tuple(named), (), 0, 0, "local-postgres", 0.0)
        self.assertEqual(confident_service(found).service_id, "cylinder-endoscopy")
        asked = [{"role": "user", "text": endoscopy}]
        reading, grounded = read_turn(asked), ground_conversation(asked, read_turn(asked))
        self.assertTrue(grounded.should_retrieve)
        reply = compose_reply(asked, reading, None, found, grounded)
        self.assertIn("эндоскоп", reply.casefold())
        self.assertIn("машину", reply.casefold())
        self.assertNotIn("цен", reply.casefold())
        self.assertNotIn("наличи", reply.casefold())
        self.assertEqual(reply.count("?"), 1)

    def test_mixed_follow_up_keeps_every_part(self) -> None:
        messages = [
            {"role": "user", "text": "Сколько стоит замена масла на Kia Rio 2018?"},
            {"role": "assistant", "text": "Точной цены для Kia Rio, 2018 здесь нет."},
            {"role": "user", "text": "А фильтр у вас есть? И ещё стучит подвеска слева."},
        ]
        reading, grounded, reply = _turn(messages)
        self.assertTrue(grounded.skip_model)
        self.assertTrue(grounded.fresh_symptom)
        self.assertTrue(grounded.asks_equipment)
        self.assertEqual(grounded.equipment_item.casefold(), "фильтр")
        folded = reply.casefold()
        self.assertIn("наличи", folded)
        self.assertIn("подвеск", folded)
        self.assertIn("rio", folded)
        self.assertNotIn("масл", folded)
        self.assertNotIn("стучит подвеска слева", folded)
        self.assertEqual(reply.count("?"), 1)

        paraphrase = [
            messages[0],
            messages[1],
            {"role": "user", "text": "Скажите, масляный фильтр в наличии? Слева ещё стучит подвеска."},
        ]
        reading, grounded, reply = _turn(paraphrase)
        self.assertTrue(grounded.skip_model)
        self.assertTrue(grounded.fresh_symptom)
        self.assertEqual((grounded.equipment_item or "").casefold(), "фильтр")
        folded = reply.casefold()
        self.assertIn("наличи", folded)
        self.assertIn("подвеск", folded)
        self.assertIn("слева", folded)
        self.assertIn("rio", folded)
        self.assertNotIn("масл", folded)
        self.assertNotIn("замена масла", folded)
        self.assertEqual(reply.count("?"), 1)

        vague = [
            messages[0],
            messages[1],
            {"role": "user", "text": "Сколько это стоит? И посмотрите там ещё что-нибудь."},
        ]
        reading, grounded, reply = _turn(vague)
        self.assertFalse(grounded.skip_model)
        self.assertIn("масл", (grounded.service or "").casefold())
        self.assertNotIn("посмотр", (grounded.service or "").casefold())
        folded = reply.casefold()
        self.assertIn("цен", folded)
        self.assertIn("масл", folded)
        self.assertIn("?", reply)
        self.assertLessEqual(reply.count("?"), 1)

    def test_local_capability_and_price_name_the_catalog_only(self) -> None:
        text = (
            "Здравствуйте! У меня Honda Civic 2009 года. Есть подозрение, что где-то подсасывает воздух. "
            "Можно у вас в Саратове проверить это дымогенератором и сколько будет стоить такая проверка?"
        )
        messages = [{"role": "user", "text": text}]
        reading = read_turn(messages)
        grounded = ground_conversation(messages, reading)
        self.assertEqual(grounded.city, "Саратове")
        self.assertEqual(grounded.stated_vehicle, "Honda Civic")
        self.assertTrue(grounded.skip_model)
        self.assertFalse(grounded.service)
        ranked = rank_services(_catalog(), text, limit=3)
        self.assertEqual(ranked[0].service_id, "intake-smoke-test")
        found = RetrievalResult(tuple(ranked), (), 0, 0, "local-postgres", 0.0)
        self.assertEqual(confident_service(found).service_id, "intake-smoke-test")
        reply = compose_reply(messages, reading, None, found, grounded)
        folded = reply.casefold()
        self.assertIn("каталоге", folded)
        self.assertIn("дымогенератор", folded)
        self.assertIn("в саратове", folded)
        self.assertIn("стоит", folded)
        self.assertIn("составлю", folded)
        self.assertNotIn("уточнить в сервисе", folded)
        self.assertNotIn("у нас", folded)
        self.assertNotIn("civic", folded)
        self.assertNotIn("2009", reply)
        self.assertNotIn("точной цены", folded)
        self.assertNotIn("у вас проверить", folded)
        self.assertEqual(reply.count("?"), 0)

        other = (
            "Добрый день. Похоже, подсасывает воздух. "
            "В Саратове сможете проверить дымогенератором, и какая цена?"
        )
        paraphrased = [{"role": "user", "text": other}]
        reading = read_turn(paraphrased)
        grounded = ground_conversation(paraphrased, reading)
        self.assertEqual(grounded.city, "Саратове")
        self.assertTrue(reading.asks_price)
        ranked = rank_services(_catalog(), other, limit=3)
        found = RetrievalResult(tuple(ranked), (), 0, 0, "local-postgres", 0.0)
        self.assertEqual(confident_service(found).service_id, "intake-smoke-test")
        reply = compose_reply(paraphrased, reading, None, found, grounded)
        folded = reply.casefold()
        self.assertIn("каталоге", folded)
        self.assertIn("в саратове", folded)
        self.assertIn("стоит", folded)
        self.assertNotIn("точной цены", folded)

    def test_scope_arithmetic_sum_and_phone_stay_on_the_fast_path(self) -> None:
        greeting = [{"role": "user", "text": "Привет"}]
        reading, grounded, reply = _turn(greeting)
        self.assertTrue(reading.social_only)
        self.assertTrue(reply.casefold().startswith("здравствуйте"))
        self.assertLessEqual(reply.count("?"), 1)

        math = [{"role": "user", "text": "Сколько будет 2 + 2?"}]
        reading, grounded, reply = _turn(math)
        self.assertTrue(reading.out_of_scope)
        self.assertFalse(reading.asks_price)
        self.assertFalse(reading.needs_extraction)
        self.assertIn("автосервис", reply.casefold())
        self.assertNotIn("4", reply)

        quoted = [{"role": "user", "text": "Запчасти 3 500, работа 2 000, сколько вместе?"}]
        reading, grounded, reply = _turn(quoted)
        self.assertEqual(grounded.stated_total, 5500)
        self.assertTrue(grounded.skip_model)
        self.assertFalse(reading.needs_extraction)
        self.assertIn("5 500", reply)
        self.assertNotIn("точной цены", reply.casefold())

        phone = [{"role": "user", "text": "Какой телефон у сервиса?"}]
        reading, grounded, reply = _turn(phone)
        self.assertTrue(reading.asks_contact)
        self.assertFalse(reading.needs_extraction)
        self.assertIn("номера телефона у меня нет", reply.casefold())
        self.assertNotIn("?", reply)

        one = {"phone": "+7 900 000-00-01"}
        several = {"contacts": [
            {"workshop": "Центр", "phone": "+7 900 000-00-01"},
            {"workshop": "Север", "phone": "+7 900 000-00-02"},
        ]}
        with mock.patch("webapp.customer_voice.verified_business", return_value=one):
            _reading, _grounded, named = _turn(phone)
        self.assertIn("+7 900 000-00-01", named)
        self.assertNotIn("?", named)
        with mock.patch("webapp.customer_voice.verified_business", return_value=several):
            _reading, _grounded, choice = _turn(phone)
        self.assertIn("центр", choice.casefold())
        self.assertIn("север", choice.casefold())
        self.assertEqual(choice.count("?"), 1)
        self.assertNotIn("+7", choice)

        inherited = [
            {"role": "user", "text": "Нужно поменять масло на Kia Rio 2018"},
            {"role": "assistant", "text": "Понял."},
            {"role": "user", "text": "А сколько стоит?"},
        ]
        reading, grounded, reply = _turn(inherited)
        self.assertIn("масл", (grounded.service or "").casefold())
        self.assertTrue(reading.asks_price)
        self.assertTrue(grounded.skip_model)
        self.assertIn("цен", reply.casefold())
        self.assertIn("масл", reply.casefold())


if __name__ == "__main__":
    unittest.main()
