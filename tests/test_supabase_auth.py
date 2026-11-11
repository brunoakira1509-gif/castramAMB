import io
import json
import os
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_auth import EmailConfirmationRequired, InvalidCredentials, SupabaseAuth


class SupabaseAuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = SupabaseAuth('https://project.supabase.co', 'sb_publishable_test')

    @patch('supabase_auth.urlopen')
    def test_sign_in_sends_email_and_password_to_password_grant(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({
            'access_token': 'token',
            'user': {'email': 'ana@example.com'},
        }).encode()

        result = self.auth.sign_in('ana@example.com', 'password123')

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://project.supabase.co/auth/v1/token?grant_type=password')
        self.assertEqual(json.loads(request.data), {'email': 'ana@example.com', 'password': 'password123'})
        self.assertEqual(request.get_header('Apikey'), 'sb_publishable_test')
        self.assertEqual(result['access_token'], 'token')

    @patch('supabase_auth.urlopen')
    def test_invalid_credentials_are_classified(self, urlopen):
        urlopen.side_effect = HTTPError(
            'https://project.supabase.co/auth/v1/token?grant_type=password',
            400,
            'Bad Request',
            {},
            io.BytesIO(b'{"code":"invalid_credentials","message":"Invalid login credentials"}'),
        )

        with self.assertRaises(InvalidCredentials):
            self.auth.sign_in('ana@example.com', 'wrong')

    @patch('supabase_auth.urlopen')
    def test_sign_up_without_session_requires_email_confirmation(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({
            'user': {'email': 'ana@example.com'},
        }).encode()

        with self.assertRaises(EmailConfirmationRequired):
            self.auth.sign_up('ana@example.com', 'password123')

    @patch('supabase_auth.urlopen')
    def test_password_change_uses_authenticated_user_token(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{}'

        self.auth.update_password('user-access-token', 'new-password')

        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, 'PUT')
        self.assertEqual(request.full_url, 'https://project.supabase.co/auth/v1/user')
        self.assertEqual(request.get_header('Authorization'), 'Bearer user-access-token')
        self.assertEqual(json.loads(request.data), {'password': 'new-password'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
