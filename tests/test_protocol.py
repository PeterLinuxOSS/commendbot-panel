import pytest

from commendbot_panel.ipc.protocol import (
    CREDENTIALS,
    Message,
    MessageReader,
    ProtocolError,
    decode,
    encode,
    parse_bool,
)


# A1 — bool("0") was True, which is why "Auto-Reconnect off" never turned off.
def test_parse_bool_treats_zero_as_false():
    assert parse_bool("0") is False
    assert parse_bool("1") is True


def test_parse_bool_accepts_the_spelled_out_negatives():
    assert [parse_bool(v) for v in ("false", "NO", " off ", "")] == [False, False, False, False]


def test_parse_bool_treats_any_other_word_as_true():
    assert parse_bool("yes") is True
    assert parse_bool("whatever") is True


def test_encode_terminates_the_line_with_a_newline():
    assert encode("STARTED") == b"STARTED\n"


def test_encode_stringifies_non_string_arguments():
    assert encode("HELLO", "tok", 76561198012345678) == b"HELLO tok 76561198012345678\n"


def test_decode_upper_cases_the_verb_and_keeps_the_arguments():
    message = decode("hello tok 42")
    assert message.verb == "HELLO"
    assert message.args == ("tok", "42")


def test_decode_rejects_an_empty_line():
    with pytest.raises(ProtocolError):
        decode("   ")


def test_decode_rejects_unbalanced_quoting():
    with pytest.raises(ProtocolError):
        decode('CREDENTIALS "unclosed')


def test_a_password_containing_a_space_survives_encode_and_decode():
    original = Message(CREDENTIALS, ("bot_one", "hunter 2 pass"))
    restored = decode(original.encode().decode("utf-8"))
    assert restored == original
    assert restored.arg(1) == "hunter 2 pass"


def test_arg_returns_the_default_when_the_argument_was_not_sent():
    assert Message("CONNECT").arg(0, "none") == "none"


def test_flags_reads_key_value_arguments_and_ignores_the_rest():
    assert Message("SETTINGS", ("autoreconnect=0", "junk", "autostart=1")).flags() == {
        "autoreconnect": "0",
        "autostart": "1",
    }


# A20 — the old protocol had no framing, so a split or merged read matched nothing.
def test_message_reader_reassembles_a_message_split_across_two_chunks():
    reader = MessageReader()
    assert reader.feed(b"HELLO tok 7656") == []
    assert [m.args for m in reader.feed(b"1198012345678\n")] == [("tok", "76561198012345678")]


# A20 — two messages arriving in one read must not be treated as one blob.
def test_message_reader_splits_two_messages_arriving_in_one_chunk():
    reader = MessageReader()
    messages = reader.feed(b"STARTED\nBYE\n")
    assert [m.verb for m in messages] == ["STARTED", "BYE"]


def test_message_reader_holds_back_a_trailing_partial_line():
    reader = MessageReader()
    assert [m.verb for m in reader.feed(b"STARTED\nBY")] == ["STARTED"]
    assert [m.verb for m in reader.feed(b"E\n")] == ["BYE"]


def test_message_reader_drops_blank_lines():
    assert MessageReader().feed(b"\n\nSTARTED\n\n")[0].verb == "STARTED"


def test_message_reader_rejects_a_line_longer_than_the_limit():
    reader = MessageReader(max_line=16)
    with pytest.raises(ProtocolError):
        reader.feed(b"X" * 17)
