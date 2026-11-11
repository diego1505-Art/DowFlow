import unittest

from downloader.strategy_selector import (
    MediaInfo,
    StrategySelector,
    YtdlpFragmentsStrategy,
    YtdlpMonoStrategy,
)


class StrategySelectorTests(unittest.TestCase):
    def test_direct_media_url_uses_mono_strategy_without_network_probe(self):
        info = MediaInfo.infer_from_url("https://cdn.example.test/media/video.mp4")
        strategy = StrategySelector(fragment_connections=16).choose(info)

        self.assertIsInstance(strategy, YtdlpMonoStrategy)
        self.assertEqual(strategy.yt_dlp_options(), {"concurrent_fragment_downloads": 1})

    def test_unknown_url_keeps_safe_fragment_strategy(self):
        info = MediaInfo.infer_from_url("https://www.youtube.com/watch?v=abc")
        strategy = StrategySelector(fragment_connections=16).choose(info)

        self.assertIsInstance(strategy, YtdlpFragmentsStrategy)
        self.assertEqual(strategy.yt_dlp_options(), {"concurrent_fragment_downloads": 16})

    def test_explicit_fragment_metadata_wins_over_url_shape(self):
        info = MediaInfo(
            url="https://cdn.example.test/stream",
            is_fragmented=True,
        )
        strategy = StrategySelector(fragment_connections=8).choose(info)

        self.assertIsInstance(strategy, YtdlpFragmentsStrategy)
        self.assertEqual(strategy.yt_dlp_options()["concurrent_fragment_downloads"], 8)

    def test_ytdlp_info_detects_manifest_protocols(self):
        info = MediaInfo.from_ytdlp_info(
            "https://example.test/watch",
            {
                "formats": [
                    {"protocol": "https"},
                    {"protocol": "m3u8_native"},
                ]
            },
        )

        self.assertTrue(info.is_fragmented)
        self.assertIsInstance(StrategySelector().choose(info), YtdlpFragmentsStrategy)

    def test_unknown_fragment_connection_count_is_clamped(self):
        strategy = StrategySelector(fragment_connections=0).choose(
            MediaInfo("https://example.test/watch")
        )

        self.assertEqual(strategy.yt_dlp_options()["concurrent_fragment_downloads"], 1)


if __name__ == "__main__":
    unittest.main()
