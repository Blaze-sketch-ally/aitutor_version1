# Analytics package initializer

from .tracker import track_event, log_query
from .recommender import get_recommendations

__all__ = [
    "track_event",
    "log_query",
    "get_recommendations"
]