from app.integrations.base import ProviderError, RemoteDoc, Provider
from app.integrations.gdrive import GoogleDriveProvider
from app.integrations.github import GitHubIssuesProvider
from app.integrations.notion import NotionProvider
from app.integrations.slack import SlackProvider

PROVIDERS = {"notion": NotionProvider, "gdrive": GoogleDriveProvider, "slack": SlackProvider, "github": GitHubIssuesProvider}

__all__ = ["PROVIDERS", "Provider", "ProviderError", "RemoteDoc", "NotionProvider", "GoogleDriveProvider", "SlackProvider", "GitHubIssuesProvider"]
