"""Download strategies.

Each strategy encapsulates *one* way of turning a resolved document into a local
file (or a final URL). Strategies are independent and must never raise into the
pipeline: failures are reported through `DownloadResult`.
"""

from strategies.api_query import ApiQueryStrategy
from strategies.base import DownloadStrategy
from strategies.browser_automation import BrowserAutomationStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy
from strategies.session_cookie import SessionCookieStrategy
from strategies.viewer_to_pdf import ViewerToPdfStrategy

__all__ = [
    "DownloadStrategy",
    "DirectDownloadStrategy",
    "ViewerToPdfStrategy",
    "ApiQueryStrategy",
    "HtmlScrapeStrategy",
    "SessionCookieStrategy",
    "BrowserAutomationStrategy",
]
