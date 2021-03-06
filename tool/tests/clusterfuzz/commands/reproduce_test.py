"""Test the module for the 'reproduce' command"""
# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import mock

from clusterfuzz import binary_providers
from clusterfuzz.commands import reproduce
from error import error
from tests import libs
from test_libs import helpers


class WarnUnreproducibleIfNeeded(helpers.ExtendedTestCase):
  """Test warn_unreproducible_if_needed."""

  def setUp(self):
    helpers.patch(self, ['clusterfuzz.commands.reproduce.logger.info'])

  def test_warn(self):
    """Test warn."""
    reproduce.warn_unreproducible_if_needed(
        mock.Mock(reproducible=False, gestures='gestures'))

    self.assertEqual(2, self.mock.info.call_count)

  def test_not_warn(self):
    """Test warn."""
    reproduce.warn_unreproducible_if_needed(
        mock.Mock(reproducible=True, gestures=None))
    self.assertEqual(0, self.mock.info.call_count)


class ExecuteTest(helpers.ExtendedTestCase):
  """Test execute."""

  def setUp(self):
    self.suppress_logging_methods()
    self.chrome_src = '/usr/local/google/home/user/repos/chromium/src'
    self.mock_os_environment({'V8_SRC': '/v8/src', 'CHROME_SRC': '/pdf/src'})
    helpers.patch(self, [
        'clusterfuzz.common.ensure_important_dirs',
        'clusterfuzz.commands.reproduce.create_builder_class',
        'clusterfuzz.commands.reproduce.get_definition',
        'clusterfuzz.commands.reproduce.get_testcase_and_identity',
        'clusterfuzz.testcase.Testcase.get_testcase_path',
    ])
    self.builder = mock.Mock(symbolizer_path='/path/to/symbolizer')
    self.reproducer = mock.Mock()
    self.definition = mock.Mock()

    self.definition.reproducer.return_value = self.reproducer

    self.mock.get_definition.return_value = self.definition
    self.mock.create_builder_class.return_value = self.builder

    self.testcase = mock.Mock(
        id='1234', build_url='chrome_build_url', revision=123456,
        job_type='linux_asan_d8', reproducible=True,
        reproduction_args='--always-opt', platform='linux')
    self.mock.get_testcase_and_identity.return_value = (
        self.testcase, 'identity@something')
    self.options = libs.make_options(
        testcase_id=str(self.testcase.id),
        extra_log_params={
            'identity': 'identity@something',
            'job_type': self.testcase.job_type,
            'platform': self.testcase.platform,
            'reproducible': self.testcase.reproducible
        }
    )

  def test_grab_data_with_download(self):
    """Ensures all method calls are made correctly when downloading."""
    self.definition.binary_name = 'defined_binary'
    self.testcase.stacktrace_lines = [
        {'content': 'incorrect'}, {'content': '[Environment] A = b'},
        {'content': ('Running command: path/to/stacktrace_binary --args --arg2 '
                     '/path/to/testcase')}]

    self.options.build = 'download'
    reproduce.execute(**vars(self.options))

    self.mock.get_testcase_and_identity.assert_called_once_with(
        self.testcase.id, False)
    self.builder.assert_called_once_with(
        testcase=self.testcase, definition=self.definition,
        options=self.options)
    self.definition.reproducer.assert_called_once_with(
        binary_provider=self.builder.return_value,
        definition=self.definition,
        testcase=self.testcase,
        sanitizer=self.definition.sanitizer,
        options=self.options)
    self.builder.return_value.build.assert_called_once_with()
    self.mock.ensure_important_dirs.assert_called_once_with()

  def test_grab_data_standalone(self):
    """Ensures all method calls are made correctly when building locally."""
    self.options.build = 'standalone'
    reproduce.execute(**vars(self.options))

    self.mock.get_testcase_and_identity.assert_called_once_with(
        self.testcase.id, False)
    self.builder.assert_called_once_with(
        testcase=self.testcase,
        definition=self.definition,
        options=self.options)
    self.definition.reproducer.assert_called_once_with(
        binary_provider=self.builder.return_value,
        definition=self.definition,
        testcase=self.testcase,
        sanitizer=self.definition.sanitizer,
        options=self.options)
    self.builder.return_value.build.assert_called_once_with()
    self.mock.ensure_important_dirs.assert_called_once_with()


class CreateBuilderClassTest(helpers.ExtendedTestCase):
  """Tests create_builder_class."""

  def test_download(self):
    """Tests construct downloaded binary class."""
    definition = mock.Mock(builder=binary_providers.LibfuzzerAndAflBuilder)
    klass = reproduce.create_builder_class('download', definition)

    self.assertEqual('DownloadedBinaryLibfuzzerAndAflBuilder', klass.__name__)


class SendRequestTest(helpers.ExtendedTestCase):
  """Test send_request."""

  def setUp(self):
    helpers.patch(self, [
        'clusterfuzz.common.get_stored_auth_header',
        'clusterfuzz.common.store_auth_header',
        'clusterfuzz.commands.reproduce.get_verification_header',
        'clusterfuzz.common.post',
        'time.sleep'
    ])

  def test_correct_stored_authorization(self):
    """Ensures that the testcase info is returned when stored auth is correct"""

    response_headers = {
        reproduce.CLUSTERFUZZ_AUTH_HEADER: 'Bearer 12345',
        reproduce.CLUSTERFUZZ_AUTH_IDENTITY: 'identity@something'}
    response_dict = {
        'id': '12345',
        'crash_type': 'Bad Crash',
        'crash_state': ['Halted']}

    self.mock.get_stored_auth_header.return_value = 'Bearer 12345'
    self.mock.post.side_effect = [
        mock.Mock(status_code=500, text='', headers=''),
        mock.Mock(status_code=500, text='', headers=''),
        mock.Mock(
            status_code=200,
            text=json.dumps(response_dict),
            headers=response_headers),
    ]

    response = reproduce.send_request('url', 'data')

    self.assert_exact_calls(self.mock.get_stored_auth_header, [mock.call()])
    self.assert_exact_calls(
        self.mock.store_auth_header, [mock.call('Bearer 12345')])
    self.assert_exact_calls(self.mock.post, [
        mock.call(
            url='url', data='data', allow_redirects=True,
            headers={'Authorization': 'Bearer 12345',
                     'User-Agent': 'clusterfuzz-tools'})
    ] * 3)
    self.assertEqual(200, response.status_code)
    self.assertEqual(
        'identity@something',
        response.headers[reproduce.CLUSTERFUZZ_AUTH_IDENTITY])

  def test_incorrect_stored_header(self):
    """Tests when the header is stored, but has expired/is invalid."""

    response_headers = {reproduce.CLUSTERFUZZ_AUTH_HEADER: 'Bearer 12345'}
    response_dict = {
        'id': '12345',
        'crash_type': 'Bad Crash',
        'crash_state': ['Halted']}

    self.mock.post.side_effect = [
        mock.Mock(status_code=401),
        mock.Mock(status_code=200,
                  text=json.dumps(response_dict),
                  headers=response_headers)]
    self.mock.get_stored_auth_header.return_value = 'Bearer 12345'
    self.mock.get_verification_header.return_value = 'VerificationCode 12345'

    response = reproduce.send_request('url', 'data')

    self.assert_exact_calls(self.mock.get_stored_auth_header, [mock.call()])
    self.assert_exact_calls(self.mock.get_verification_header, [mock.call()])
    self.assert_exact_calls(self.mock.post, [
        mock.call(
            allow_redirects=True, url='url', data='data',
            headers={'Authorization': 'Bearer 12345',
                     'User-Agent': 'clusterfuzz-tools'}),
        mock.call(
            allow_redirects=True, data='data', url='url',
            headers={'Authorization': 'VerificationCode 12345',
                     'User-Agent': 'clusterfuzz-tools'})
    ])
    self.assert_exact_calls(self.mock.store_auth_header, [
        mock.call('Bearer 12345')])
    self.assertEqual(200, response.status_code)


  def test_correct_verification_auth(self):
    """Tests grabbing testcase info when the local header is invalid."""

    response_headers = {reproduce.CLUSTERFUZZ_AUTH_HEADER: 'Bearer 12345'}
    response_dict = {
        'id': '12345',
        'crash_type': 'Bad Crash',
        'crash_state': ['Halted']}

    self.mock.get_stored_auth_header.return_value = None
    self.mock.get_verification_header.return_value = 'VerificationCode 12345'
    self.mock.post.return_value = mock.Mock(
        status_code=200,
        text=json.dumps(response_dict),
        headers=response_headers)

    response = reproduce.send_request('url', 'data')

    self.assert_exact_calls(self.mock.get_stored_auth_header, [mock.call()])
    self.assert_exact_calls(self.mock.get_verification_header, [mock.call()])
    self.assert_exact_calls(self.mock.store_auth_header, [
        mock.call('Bearer 12345')])
    self.assert_exact_calls(self.mock.post, [
        mock.call(
            allow_redirects=True, data='data', url='url',
            headers={'Authorization': 'VerificationCode 12345',
                     'User-Agent': 'clusterfuzz-tools'})
    ])
    self.assertEqual(200, response.status_code)

  def test_incorrect_authorization(self):
    """Ensures that when auth is incorrect the right exception is thrown"""

    response_headers = {
        reproduce.CLUSTERFUZZ_AUTH_HEADER: 'Bearer 12345',
        reproduce.CLUSTERFUZZ_AUTH_IDENTITY: 'identity@something'}
    response_dict = {
        'status': 401,
        'type': 'UnauthorizedException',
        'message': {
            'Invalid verification code (12345)': {
                'error': 'invalid_grant',
                'error_description': 'Bad Request'}},
        'params': {
            'testcaseId': ['999']},
        'email': 'test@email.com'}

    self.mock.get_stored_auth_header.return_value = 'Bearer 12345'
    self.mock.get_verification_header.return_value = 'VerificationCode 12345'
    self.mock.post.return_value = mock.Mock(
        status_code=401,
        text=json.dumps(response_dict),
        headers=response_headers)

    with self.assertRaises(error.ClusterFuzzError) as cm:
      reproduce.send_request('url', 'data')

    self.assertEqual(401, cm.exception.status_code)
    self.assert_exact_calls(
        self.mock.post,
        [
            mock.call(
                allow_redirects=True, url='url', data='data',
                headers={'Authorization': 'Bearer 12345',
                         'User-Agent': 'clusterfuzz-tools'})
        ] + [
            mock.call(
                allow_redirects=True, url='url', data='data',
                headers={'Authorization': 'VerificationCode 12345',
                         'User-Agent': 'clusterfuzz-tools'})
        ] * (reproduce.RETRY_COUNT - 1)
    )


class GetTestcaseAndIdentityTest(helpers.ExtendedTestCase):
  """Test get_testcase."""

  def setUp(self):
    helpers.patch(self, [
        'clusterfuzz.commands.reproduce.send_request',
        'clusterfuzz.testcase.create'
    ])

  def test_succeed(self):
    """Test succeed."""
    self.mock.send_request.return_value = mock.Mock(
        text='{"test": "ok"}',
        headers={reproduce.CLUSTERFUZZ_AUTH_IDENTITY: 'identity'})
    self.mock.create.return_value = 'dummy testcase'
    self.assertEqual(
        ('dummy testcase', 'identity'),
        reproduce.get_testcase_and_identity('12345'))

    self.mock.send_request.assert_called_once_with(
        reproduce.CLUSTERFUZZ_TESTCASE_INFO_URL, '{"testcaseId": "12345"}')

  def test_404(self):
    """Test 404."""
    self.mock.send_request.side_effect = error.ClusterFuzzError(
        404, 'resp', 'identity')
    with self.assertRaises(error.InvalidTestcaseIdError) as cm:
      reproduce.get_testcase_and_identity('12345')

    self.assertIn('12345', cm.exception.message)
    self.mock.send_request.assert_called_once_with(
        reproduce.CLUSTERFUZZ_TESTCASE_INFO_URL, '{"testcaseId": "12345"}')

  def test_401(self):
    """Test 401."""
    self.mock.send_request.side_effect = error.ClusterFuzzError(
        401, 'resp', 'identity@something')
    with self.assertRaises(error.UnauthorizedError) as cm:
      reproduce.get_testcase_and_identity('12345')

    self.assertIn('12345', cm.exception.message)
    self.assertIn('identity@something', cm.exception.message)
    self.mock.send_request.assert_called_once_with(
        reproduce.CLUSTERFUZZ_TESTCASE_INFO_URL, '{"testcaseId": "12345"}')

  def test_error(self):
    """Test other error."""
    self.mock.send_request.side_effect = error.ClusterFuzzError(
        500, 'resp', 'identity@something')
    with self.assertRaises(error.ClusterFuzzError) as cm:
      reproduce.get_testcase_and_identity('12345')

    self.assertEqual(500, cm.exception.status_code)
    self.assertIn('resp', cm.exception.message)
    self.assertIn('identity@something', cm.exception.message)
    self.mock.send_request.assert_called_once_with(
        reproduce.CLUSTERFUZZ_TESTCASE_INFO_URL, '{"testcaseId": "12345"}')


class GetVerificationHeaderTest(helpers.ExtendedTestCase):
  """Tests the get_verification_header method"""

  def setUp(self):
    helpers.patch(self, [
        'webbrowser.open',
        'clusterfuzz.common.ask'])
    self.mock.ask.return_value = '12345'

  def test_returns_correct_header(self):
    """Tests that the correct token with header is returned."""

    response = reproduce.get_verification_header()

    self.mock.open.assert_has_calls([mock.call(
        reproduce.GOOGLE_OAUTH_URL,
        new=1,
        autoraise=True)])
    self.assertEqual(response, 'VerificationCode 12345')


class SuppressOutputTest(helpers.ExtendedTestCase):
  """Test SuppressOutput."""

  def setUp(self):
    helpers.patch(self, ['os.dup', 'os.open', 'os.close', 'os.dup2'])

    def dup(number):
      if number == 1:
        return 'out'
      elif number == 2:
        return 'err'
    self.mock.dup.side_effect = dup

  def test_suppress(self):
    """Test suppressing output."""
    with reproduce.SuppressOutput():
      pass

    self.assert_exact_calls(self.mock.dup, [mock.call(1), mock.call(2)])
    self.assert_exact_calls(self.mock.close, [mock.call(1), mock.call(2)])
    self.mock.open.assert_called_once_with(os.devnull, os.O_RDWR)
    self.assert_exact_calls(
        self.mock.dup2, [mock.call('out', 1), mock.call('err', 2)])

  def test_exception(self):
    """Test absorbing exception."""
    with reproduce.SuppressOutput():
      raise Exception('test_exc')

    self.assert_exact_calls(self.mock.dup, [mock.call(1), mock.call(2)])
    self.assert_exact_calls(self.mock.close, [mock.call(1), mock.call(2)])
    self.mock.open.assert_called_once_with(os.devnull, os.O_RDWR)
    self.assert_exact_calls(
        self.mock.dup2, [mock.call('out', 1), mock.call('err', 2)])


class GetDefinitionTest(helpers.ExtendedTestCase):
  """Tests getting binary definitions."""

  def setUp(self):
    helpers.patch(self, ['clusterfuzz.commands.reproduce.get_supported_jobs'])
    self.v8_definition = mock.Mock()
    self.chromium_definition = mock.Mock()
    self.mock.get_supported_jobs.return_value = {
        'chromium': {'libfuzzer_chrome_msan': self.chromium_definition},
        'standalone': {'linux_asan_d8': self.v8_definition}
    }

  def test_download_param(self):
    """Tests when the build_param is download"""
    result = reproduce.get_definition(
        'libfuzzer_chrome_msan', '123', 'download')
    self.assertEqual(result, self.chromium_definition)

    result = reproduce.get_definition('linux_asan_d8', '123', 'download')
    self.assertEqual(result, self.v8_definition)

    with self.assertRaises(error.JobTypeNotSupportedError):
      result = reproduce.get_definition(
          'fuzzlibber_nasm', '123', 'download')

  def test_default(self):
    """Tests when the build is not specified."""
    result = reproduce.get_definition('linux_asan_d8', '123', '')
    self.assertEqual(result, self.v8_definition)

    result = reproduce.get_definition('libfuzzer_chrome_msan', '123', '')
    self.assertEqual(result, self.chromium_definition)

  def test_standalone(self):
    """Tests when the build is standalone."""
    result = reproduce.get_definition('linux_asan_d8', '123', 'standalone')
    self.assertEqual(result, self.v8_definition)

    with self.assertRaises(error.JobTypeNotSupportedError):
      result = reproduce.get_definition('fuzzlibber_nasm', '123', 'standalone')

  def test_chromium(self):
    """Tests when the build is chromium."""
    result = reproduce.get_definition(
        'libfuzzer_chrome_msan', '123', 'chromium')
    self.assertEqual(result, self.chromium_definition)

    with self.assertRaises(error.JobTypeNotSupportedError):
      result = reproduce.get_definition('fuzzlibber_nasm', '123', 'chromium')


class GetSupportedJobsTest(helpers.ExtendedTestCase):
  """Tests the get_supported_jobs method."""

  def test_raise_from_key_error(self):
    """Tests that a BadJobTypeDefinition error is raised when parsing fails."""
    helpers.patch(self, [
        'clusterfuzz.commands.reproduce.build_definition'])
    self.mock.build_definition.side_effect = KeyError

    with self.assertRaises(error.BadJobTypeDefinitionError):
      reproduce.get_supported_jobs()

  def test_get(self):
    """Test getting supported job types."""
    results = reproduce.get_supported_jobs()
    self.assertIn('chromium', results)
    self.assertIn('libfuzzer_chrome_ubsan', results['chromium'])
    self.assertIn('standalone', results)
    self.assertIn('linux_asan_pdfium', results['standalone'])
