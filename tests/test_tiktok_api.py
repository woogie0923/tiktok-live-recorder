import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_api import TikTokAPI  # noqa: E402
from utils.custom_exceptions import UserLiveError  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return FakeResponse(self.responses.pop(0))


def build_api(*responses):
    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"
    api.http_client = FakeHttpClient(list(responses))
    return api


def test_is_room_alive_rejects_fake_check_alive_positive():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {"message": "Request params error"}, "status_code": 10011},
    )

    assert api.is_room_alive("123") is False


def test_is_room_alive_accepts_confirmed_stream_room():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {"pull_data": {"stream_data": '{"data": {}}'}}
                },
            },
            "status_code": 0,
        },
    )

    assert api.is_room_alive("123") is True


def test_is_room_alive_keeps_restricted_live_as_alive():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {}, "status_code": 4003110},
    )

    assert api.is_room_alive("123") is True


def test_is_room_alive_skips_room_info_when_check_alive_is_false():
    api = build_api({"data": [{"alive": False, "room_id": 123}], "status_code": 0})

    assert api.is_room_alive("123") is False
    assert len(api.http_client.urls) == 1


def test_is_room_alive_rejects_null_check_alive_data():
    api = build_api({"data": None, "status_code": 0})

    assert api.is_room_alive("123") is False
    assert len(api.http_client.urls) == 1


def test_is_room_alive_rejects_null_room_info_data():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": None, "status_code": 0},
    )

    assert api.is_room_alive("123") is False


def test_is_room_alive_rejects_ended_room_with_stale_stream_urls():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {
            "data": {
                "status": 4,
                "finish_time": 1784118433,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {"stream_data": '{"data": {}}'}
                    },
                    "flv_pull_url": {"HD1": "https://example.com/stale.flv"},
                },
            },
            "status_code": 0,
        },
    )

    assert api.is_room_alive("123") is False


def test_get_live_url_rejects_ended_room_with_stale_stream_urls():
    api = build_api(
        {
            "data": {
                "status": 4,
                "finish_time": 1784118433,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {"stream_data": '{"data": {}}'}
                    },
                    "flv_pull_url": {"HD1": "https://example.com/stale.flv"},
                },
            },
            "status_code": 0,
        },
    )

    with pytest.raises(UserLiveError, match="not hosting a live stream"):
        api.get_live_url("123", user="creator")


def test_get_live_url_candidates_returns_ordered_unique_streams():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"origin": {"main": {"flv": "https://cdn/origin.flv"}},'
                                '"hd": {"main": {"flv": "https://cdn/hd.flv"}},'
                                '"ld": {"main": {"flv": "https://cdn/ld.flv"}},'
                                '"ao": {"main": {"flv": "https://cdn/audio.flv?only_audio=1"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "origin", "level": 10},
                                    {"sdk_key": "hd", "level": 3},
                                    {"sdk_key": "ld", "level": 1},
                                ]
                            },
                        }
                    },
                    "flv_pull_url": {
                        "FULL_HD1": "https://cdn/fullhd.flv",
                        "HD1": "https://cdn/hd.flv",
                        "SD1": "https://cdn/sd.flv",
                    },
                },
            },
            "status_code": 0,
        },
    )

    assert api.get_live_url_candidates("123", user="creator") == [
        "https://cdn/origin.flv",
        "https://cdn/hd.flv",
        "https://cdn/ld.flv",
        "https://cdn/fullhd.flv",
        "https://cdn/sd.flv",
    ]


def test_get_live_url_candidates_prefers_uhd_60_over_origin_and_hd():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"hd": {"main": {"flv": "https://cdn/hd.flv"}},'
                                '"uhd_60": {"main": {"flv": "https://cdn/uhd60.flv", '
                                '"sdk_params": "{\\"stream_suffix\\":\\"uhd560\\",'
                                '\\"resolution\\":\\"1080x1920\\"}"}},'
                                '"origin": {"main": {"flv": "https://cdn/origin.flv", '
                                '"sdk_params": "{\\"resolution\\":\\"1080x1920\\"}"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "origin", "level": 10},
                                    {"sdk_key": "uhd_60", "level": 6},
                                    {"sdk_key": "hd", "level": 3},
                                ]
                            },
                        }
                    },
                    "flv_pull_url": {"HD1": "https://cdn/hd.flv"},
                },
            },
            "status_code": 0,
        },
    )

    candidates = api.get_live_url_candidates("123", user="creator")
    assert candidates[0] == "https://cdn/uhd60.flv"
    assert candidates.index("https://cdn/origin.flv") < candidates.index(
        "https://cdn/hd.flv"
    )


def test_get_recording_flv_tiers_prefers_uhd_60_then_origin_only():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"hd": {"main": {"flv": "https://cdn/hd.flv", '
                                '"hls": "https://cdn/hd.m3u8"}},'
                                '"uhd_60": {"main": {"flv": "https://cdn/stream_uhd560.flv", '
                                '"hls": "https://cdn/uhd60.m3u8", '
                                '"sdk_params": "{\\"stream_suffix\\":\\"uhd560\\",'
                                '\\"resolution\\":\\"1080x1920\\"}"}},'
                                '"origin": {"main": {"flv": "https://cdn/origin.flv", '
                                '"hls": "https://cdn/origin.m3u8", '
                                '"sdk_params": "{\\"resolution\\":\\"1080x1920\\"}"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "origin", "name": "Original", "level": 10},
                                    {"sdk_key": "uhd_60", "name": "1080p60", "level": 6},
                                    {"sdk_key": "hd", "name": "720p", "level": 3},
                                ]
                            },
                        }
                    }
                },
            },
            "status_code": 0,
        },
    )

    tiers = api.get_recording_flv_tiers("123", user="creator")
    assert [tier[0] for tier in tiers] == ["uhd_60", "origin"]
    assert all(".m3u8" not in tier[2] for tier in tiers)
    assert "https://cdn/hd.flv" not in [tier[2] for tier in tiers]


def test_get_recording_flv_tiers_skips_mislabeled_uhd_60_url():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"uhd_60": {"main": {"flv": "https://cdn/stream_hd5b.flv", '
                                '"sdk_params": "{\\"stream_suffix\\":\\"hd5b\\",'
                                '\\"resolution\\":\\"720x1280\\"}"}},'
                                '"origin": {"main": {"flv": "https://cdn/stream.flv", '
                                '"sdk_params": "{\\"resolution\\":\\"1080x1920\\"}"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "origin", "name": "Original", "level": 10},
                                    {"sdk_key": "uhd_60", "name": "1080p60", "level": 6},
                                ]
                            },
                        }
                    }
                },
            },
            "status_code": 0,
        },
    )

    tiers = api.get_recording_flv_tiers("123", user="creator")
    assert tiers == [
        (
            "origin",
            "Original",
            "https://cdn/stream.flv",
            {
                "main": {
                    "flv": "https://cdn/stream.flv",
                    "sdk_params": '{"resolution":"1080x1920"}',
                }
            },
        )
    ]


def test_get_recording_flv_tiers_origin_only_skips_720p():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"hd": {"main": {"flv": "https://cdn/hd.flv"}},'
                                '"origin": {"main": {"flv": "https://cdn/origin.flv", '
                                '"sdk_params": "{\\"resolution\\":\\"1080x1920\\"}"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "origin", "name": "Original", "level": 10},
                                    {"sdk_key": "hd", "name": "720p", "level": 3},
                                ]
                            },
                        }
                    }
                },
            },
            "status_code": 0,
        },
    )

    tiers = api.get_recording_flv_tiers("123", user="creator")
    assert tiers == [
        (
            "origin",
            "Original",
            "https://cdn/origin.flv",
            {
                "main": {
                    "flv": "https://cdn/origin.flv",
                    "sdk_params": '{"resolution":"1080x1920"}',
                }
            },
        )
    ]
