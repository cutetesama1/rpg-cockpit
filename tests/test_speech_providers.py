"""Transport contracts: no vendor credentials or paid requests are required."""
import io
import json
import logging
import unittest
import urllib.error
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch

from rpg_gateway.speech import synthesize


VOICE = 'cJ90yKqmDMAuUmZ3fyB4'
MP3 = b'ID3\x04\x00\x00\xff\xfb\x90\x00'


class SpeechProviderTests(unittest.TestCase):
    def config(self, **changes):
        return SimpleNamespace(**{
            **dict(provider='elevenlabs', base_url='https://api.elevenlabs.io/v1/',
                   api_key='test-secret-never-log', model='', speed=1.5, timeout=30),
            **changes,
        })

    def call(self, config=None, mime='audio/mpeg', data=MP3, error=None, voice=VOICE):
        headers = Message(); headers['Content-Type'] = mime
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.headers = headers; response.read.return_value = data
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value = response
            if error: build.return_value.open.side_effect = error
            result = synthesize(config or self.config(), '你好。', voice)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 30)
            return result, request

    def test_elevenlabs_native_request_and_mp3_bytes(self):
        result, request = self.call()
        self.assertEqual(result, (MP3, 'audio/mpeg'))
        self.assertEqual(request.full_url, 'https://api.elevenlabs.io/v1/text-to-speech/' + VOICE)
        self.assertEqual(request.get_method(), 'POST')
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers['xi-api-key'], 'test-secret-never-log')
        self.assertNotIn('authorization', headers)
        self.assertEqual(headers['content-type'], 'application/json')
        self.assertEqual(headers['accept'], 'audio/mpeg')
        self.assertEqual(json.loads(request.data), {'text': '你好。', 'model_id': 'eleven_multilingual_v2'})

    def test_custom_model_and_per_character_voice(self):
        _, request = self.call(self.config(model='eleven_turbo_v2_5'), voice='another_voice')
        self.assertTrue(request.full_url.endswith('/text-to-speech/another_voice'))
        self.assertEqual(json.loads(request.data)['model_id'], 'eleven_turbo_v2_5')

    def test_openai_contract_is_preserved(self):
        for base in ('https://openai.test/v1', 'https://openai.test/v1/audio/speech'):
            with self.subTest(base=base):
                _, request = self.call(self.config(provider='openai', base_url=base, model='tts-1'), voice='alloy')
                self.assertEqual(request.full_url, 'https://openai.test/v1/audio/speech')
                self.assertEqual(request.get_method(), 'POST')
                headers = {k.lower(): v for k, v in request.header_items()}
                self.assertEqual(headers['authorization'], 'Bearer test-secret-never-log')
                self.assertNotIn('xi-api-key', headers)
                self.assertEqual(json.loads(request.data), {'model':'tts-1', 'voice':'alloy', 'input':'你好。', 'response_format':'mp3', 'speed':1.5})

    def test_binary_mime_aliases(self):
        for mime in ('application/octet-stream', 'audio/mp3', 'audio/mpeg'):
            with self.subTest(mime=mime):
                self.assertEqual(self.call(mime=mime)[0], (MP3, 'audio/mpeg'))

    def test_bad_audio_is_rejected(self):
        for mime, data in [('application/json', b'{}'), ('audio/mpeg', b''), ('audio/mpeg', b'x'*(8*1024*1024+1))]:
            with self.subTest(mime=mime, size=len(data)), self.assertRaises(ValueError):
                self.call(mime=mime, data=data)

    def test_http_errors_and_logs_do_not_echo_secrets(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                error = urllib.error.HTTPError('https://api.elevenlabs.io/v1', status, 'test-secret-never-log', {}, io.BytesIO(b'test-secret-never-log'))
                with self.assertLogs('rpg_gateway.speech', level=logging.INFO) as logs:
                    with self.assertRaisesRegex(ValueError, 'HTTP ' + str(status)) as caught:
                        self.call(error=error)
                output = str(caught.exception) + '\n'.join(logs.output)
                self.assertNotIn('test-secret-never-log', output)
                self.assertNotIn('你好', output)
                self.assertIn('provider=elevenlabs', output)

    def test_network_failure_is_sanitized(self):
        with self.assertLogs('rpg_gateway.speech', level=logging.INFO) as logs:
            with self.assertRaisesRegex(ValueError, '连接失败') as caught:
                self.call(error=OSError('test-secret-never-log'))
        self.assertNotIn('test-secret-never-log', str(caught.exception) + str(logs.output))

    def test_voice_path_injection_is_rejected_before_network(self):
        for voice in ('../voices', 'voice?key=secret', '', 'voice/other'):
            with self.subTest(voice=voice), patch('urllib.request.build_opener') as build:
                with self.assertRaisesRegex(ValueError, 'Voice ID'):
                    synthesize(self.config(), '你好。', voice)
                build.assert_not_called()

    def test_missing_key_is_rejected_before_network(self):
        with patch('urllib.request.build_opener') as build:
            with self.assertRaisesRegex(ValueError, 'API Key'):
                synthesize(self.config(api_key=''), '你好。', VOICE)
            build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
