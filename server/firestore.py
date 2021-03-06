from firebase_admin import _apps as firebase_apps
from firebase_admin import initialize_app
from firebase_admin.credentials import ApplicationDefault
from firebase_admin.firestore import client as firestore_client
from googleapiclient.http import build_http
from google.cloud.firestore import DELETE_FIELD
from logging import error
from logging import info
from logging import warning
from oauth2client.client import HttpAccessTokenRefreshError
from oauth2client.client import OAuth2Credentials
from oauth2client.client import Storage
from os import environ
from threading import Lock


class Firestore(object):
    """A wrapper around the Cloud Firestore database."""

    def __init__(self):
        # Only initialize Firebase once.
        if not len(firebase_apps):
            initialize_app(ApplicationDefault(), {
                'projectId': environ['GOOGLE_CLOUD_PROJECT']
            })
        self._db = firestore_client()

    def _api_key(self, service):
        """Retrieves the API key for the specified service."""

        api_key = self._db.collection('api_keys').document(service).get()
        if not api_key.exists:
            raise DataError('Missing API key for: %s' % service)

        return api_key.get('api_key')

    def google_maps_api_key(self):
        """Retrieves the Google Maps API key."""

        return self._api_key('google_maps')

    def open_weather_api_key(self):
        """Retrieves the OpenWeather API key."""

        return self._api_key('open_weather')

    def google_calendar_secrets(self):
        """Loads the Google Calendar API secrets from the database."""

        clients = self._db.collection('oauth_clients')
        secrets = clients.document('google_calendar').get()
        if not secrets.exists:
            raise DataError('Missing Google Calendar secrets')

        return secrets.to_dict()

    def google_calendar_credentials(self, key):
        """Loads and refreshes Google Calendar API credentials."""

        # Look up the user from the key.
        user = self.user(key)
        if not user:
            return None

        # Load the credentials from storage.
        try:
            json = user.get('google_calendar_credentials')
        except KeyError:
            warning('Failed to load Google Calendar credentials.')
            return None

        # Use the valid credentials.
        credentials = OAuth2Credentials.from_json(json)
        if credentials and not credentials.invalid:
            return credentials

        # Handle invalidation and expiration.
        if credentials and credentials.access_token_expired:
            try:
                info('Refreshing Google Calendar credentials.')
                credentials.refresh(build_http())
                return credentials
            except HttpAccessTokenRefreshError as e:
                warning('Google Calendar refresh failed: %s' % e)

        # Credentials are missing or refresh failed.
        warning('Deleting Google Calendar credentials.')
        self.delete_google_calendar_credentials(key)
        return None

    def update_google_calendar_credentials(self, key, credentials):
        """Updates the users's Google Calendar credentials."""

        self.update_user(key, {
            'google_calendar_credentials': credentials.to_json()})

    def delete_google_calendar_credentials(self, key):
        """Deletes the users's Google Calendar credentials."""

        self.update_user(key, {'google_calendar_credentials': DELETE_FIELD})

    def user(self, key):
        """Retrieves the user snapshot matching the specified key."""

        user = self._user_reference(key).get()
        if not user.exists:
            warning('User not found.')
            return None

        return user

    def users(self):
        """Returns an iterator over all users."""

        return self._db.collection('users').stream()

    def _user_reference(self, key):
        """Retrieves the user reference matching the specified key."""

        return self._db.collection('users').document(key)

    def set_user(self, key, data):
        """Sets the data for the user matching the specified key."""

        # Use merge to only overwrite the specified data.
        self._user_reference(key).set(data, merge=True)

    def update_user(self, key, fields):
        """Updates the fields for the user matching the specified key."""

        user = self._user_reference(key)
        if not user.get().exists:
            error('User not found for update.')
            return

        user.update(fields)


class GoogleCalendarStorage(Storage):
    """Credentials storage for the Google Calendar API using Firestore."""

    def __init__(self, key):
        super(GoogleCalendarStorage, self).__init__(lock=Lock())
        self._firestore = Firestore()
        self._key = key

    def locked_get(self):
        """Loads credentials from Firestore and attaches this storage."""

        credentials = self._firestore.google_calendar_credentials(self._key)
        if not credentials:
            return None
        credentials.set_store(self)
        return credentials

    def locked_put(self, credentials):
        """Saves credentials to Firestore."""

        self._firestore.update_google_calendar_credentials(self._key,
                                                           credentials)

    def locked_delete(self):
        """Deletes credentials from Firestore."""

        self._firestore.delete_google_calendar_credentials(self._key)


class DataError(Exception):
    """An error indicating issues retrieving data."""

    pass
