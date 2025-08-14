from enum import Enum
import json
from typing import Sequence
import praw
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
from mcp.shared.exceptions import McpError
from pydantic import BaseModel


class PostType(str, Enum):
    LINK = "link"
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    UNKNOWN = "unknown"


class RedditTools(str, Enum):
    GET_FRONTPAGE_POSTS = "get_frontpage_posts"
    GET_SUBREDDIT_INFO = "get_subreddit_info"
    GET_SUBREDDIT_HOT_POSTS = "get_subreddit_hot_posts"
    GET_SUBREDDIT_NEW_POSTS = "get_subreddit_new_posts"
    GET_SUBREDDIT_TOP_POSTS = "get_subreddit_top_posts"
    GET_SUBREDDIT_RISING_POSTS = "get_subreddit_rising_posts"
    GET_POST_CONTENT = "get_post_content"
    GET_POST_COMMENTS = "get_post_comments"
    SEARCH_REDDIT = "search_reddit"
    SEARCH_SUBREDDIT = "search_subreddit"
    SEARCH_SUBREDDITS = "search_subreddits"
    SEARCH_USER_POSTS = "search_user_posts"


class SubredditInfo(BaseModel):
    name: str
    subscriber_count: int
    description: str | None


class Post(BaseModel):
    id: str
    title: str
    author: str
    score: int
    subreddit: str
    url: str
    created_at: str
    comment_count: int
    post_type: PostType
    content: str | None


class Comment(BaseModel):
    id: str
    author: str
    body: str
    score: int
    replies: list['Comment'] = []


class Moderator(BaseModel):
    name: str


class PostDetail(BaseModel):
    post: Post
    comments: list[Comment]


class RedditServer:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id="GuixM5R4H8A7Xiyo01FueA",
            client_secret="kzE9ChaZy3bgIEvDdBRwxPEezqVB-A",
            user_agent="mcp-server-reddit v1.0"
        )

    def _get_post_type(self, submission) -> PostType:
        """Helper method to determine post type"""
        if hasattr(submission, 'post_hint'):
            if submission.post_hint == 'image':
                return PostType.IMAGE
            elif submission.post_hint == 'hosted:video' or submission.post_hint == 'rich:video':
                return PostType.VIDEO
            elif submission.post_hint == 'link':
                return PostType.LINK
        
        if submission.is_self:
            return PostType.TEXT
        
        return PostType.UNKNOWN

    def _get_post_content(self, submission) -> str | None:
        """Helper method to extract post content based on type"""
        if submission.is_self:
            return submission.selftext
        else:
            return submission.url

    def _build_post(self, submission) -> Post:
        """Helper method to build Post object from submission"""
        return Post(
            id=submission.id,
            title=submission.title,
            author=str(submission.author) if submission.author else '[deleted]',
            score=submission.score,
            subreddit=submission.subreddit.display_name,
            url=f"https://reddit.com{submission.permalink}",
            created_at=str(submission.created_utc),
            comment_count=submission.num_comments,
            post_type=self._get_post_type(submission),
            content=self._get_post_content(submission)
        )

    def get_frontpage_posts(self, limit: int = 10) -> list[Post]:
        """Get hot posts from Reddit frontpage"""
        posts = []
        for submission in self.reddit.front.hot(limit=limit):
            posts.append(self._build_post(submission))
        return posts

    def get_subreddit_info(self, subreddit_name: str) -> SubredditInfo:
        """Get information about a subreddit"""
        subreddit = self.reddit.subreddit(subreddit_name)
        return SubredditInfo(
            name=subreddit.display_name,
            subscriber_count=subreddit.subscribers,
            description=subreddit.public_description
        )

    def _build_comment_tree(self, comment, depth: int = 3) -> Comment | None:
        """Helper method to recursively build comment tree"""
        if depth <= 0 or not comment or isinstance(comment, praw.models.MoreComments):
            return None

        replies = []
        if hasattr(comment, 'replies') and depth > 1:
            for reply in comment.replies[:5]:  # Limit to 5 replies per level
                if not isinstance(reply, praw.models.MoreComments):
                    reply_comment = self._build_comment_tree(reply, depth - 1)
                    if reply_comment:
                        replies.append(reply_comment)

        return Comment(
            id=comment.id,
            author=str(comment.author) if comment.author else '[deleted]',
            body=comment.body,
            score=comment.score,
            replies=replies
        )

    def get_subreddit_hot_posts(self, subreddit_name: str, limit: int = 10) -> list[Post]:
        """Get hot posts from a specific subreddit"""
        posts = []
        subreddit = self.reddit.subreddit(subreddit_name)
        for submission in subreddit.hot(limit=limit):
            posts.append(self._build_post(submission))
        return posts

    def get_subreddit_new_posts(self, subreddit_name: str, limit: int = 10) -> list[Post]:
        """Get new posts from a specific subreddit"""
        posts = []
        subreddit = self.reddit.subreddit(subreddit_name)
        for submission in subreddit.new(limit=limit):
            posts.append(self._build_post(submission))
        return posts

    def get_subreddit_top_posts(self, subreddit_name: str, limit: int = 10, time: str = 'all') -> list[Post]:
        """Get top posts from a specific subreddit"""
        posts = []
        subreddit = self.reddit.subreddit(subreddit_name)
        time_filter = time if time else 'all'
        for submission in subreddit.top(time_filter=time_filter, limit=limit):
            posts.append(self._build_post(submission))
        return posts

    def get_subreddit_rising_posts(self, subreddit_name: str, limit: int = 10) -> list[Post]:
        """Get rising posts from a specific subreddit"""
        posts = []
        subreddit = self.reddit.subreddit(subreddit_name)
        for submission in subreddit.rising(limit=limit):
            posts.append(self._build_post(submission))
        return posts

    def get_post_content(self, post_id: str, comment_limit: int = 10, comment_depth: int = 3) -> PostDetail:
        """Get detailed content of a specific post including comments"""
        submission = self.reddit.submission(id=post_id)
        post = self._build_post(submission)

        # Fetch comments
        comments = self.get_post_comments(post_id, comment_limit)
        
        return PostDetail(post=post, comments=comments)

    def get_post_comments(self, post_id: str, limit: int = 10) -> list[Comment]:
        """Get comments from a post"""
        comments = []
        submission = self.reddit.submission(id=post_id)
        submission.comments.replace_more(limit=0)  # Remove "more comments" objects
        
        for comment in submission.comments[:limit]:
            if not isinstance(comment, praw.models.MoreComments):
                built_comment = self._build_comment_tree(comment)
                if built_comment:
                    comments.append(built_comment)
        return comments

    def search_reddit(self, query: str, sort: str = "relevance", time: str = "all", limit: int = 10) -> list[Post]:
        """Search across all of Reddit for posts matching a query"""
        posts = []
        try:
            for submission in self.reddit.subreddit("all").search(query, sort=sort, time_filter=time, limit=limit):
                posts.append(self._build_post(submission))
        except Exception as e:
            raise ValueError(f"Search failed: {str(e)}")
        return posts

    def search_subreddit(self, subreddit_name: str, query: str, sort: str = "relevance", time: str = "all", limit: int = 10) -> list[Post]:
        """Search within a specific subreddit for posts matching a query"""
        posts = []
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            for submission in subreddit.search(query, sort=sort, time_filter=time, limit=limit):
                posts.append(self._build_post(submission))
        except Exception as e:
            raise ValueError(f"Subreddit search failed: {str(e)}")
        return posts

    def search_subreddits(self, query: str, limit: int = 10) -> list[SubredditInfo]:
        """Search for subreddits by name or description"""
        subreddits = []
        try:
            for subreddit in self.reddit.subreddits.search(query, limit=limit):
                subreddits.append(SubredditInfo(
                    name=subreddit.display_name,
                    subscriber_count=subreddit.subscribers,
                    description=subreddit.public_description
                ))
        except Exception as e:
            raise ValueError(f"Subreddit search failed: {str(e)}")
        return subreddits

    def search_user_posts(self, username: str, sort: str = "new", time: str = "all", limit: int = 10) -> list[Post]:
        """Search through a user's post history"""
        posts = []
        try:
            user = self.reddit.redditor(username)
            
            if sort == "new":
                submissions = user.submissions.new(limit=limit)
            elif sort == "hot":
                submissions = user.submissions.hot(limit=limit)
            elif sort == "top":
                submissions = user.submissions.top(time_filter=time, limit=limit)
            else:
                submissions = user.submissions.new(limit=limit)
            
            for submission in submissions:
                posts.append(self._build_post(submission))
        except Exception as e:
            raise ValueError(f"User search failed: {str(e)}")
        
        return posts


async def serve() -> None:
    server = Server("mcp-reddit")
    reddit_server = RedditServer()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available Reddit tools."""
        return [
            Tool(
                name=RedditTools.GET_FRONTPAGE_POSTS.value,
                description="Get hot posts from Reddit frontpage",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of posts to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        }
                    }
                }
            ),
            Tool(
                name=RedditTools.GET_SUBREDDIT_INFO.value,
                description="Get information about a subreddit",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit (e.g. 'Python', 'news')",
                        }
                    },
                    "required": ["subreddit_name"]
                }
            ),
            Tool(
                name=RedditTools.GET_SUBREDDIT_HOT_POSTS.value,
                description="Get hot posts from a specific subreddit",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit (e.g. 'Python', 'news')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of posts to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["subreddit_name"]
                }
            ),
            Tool(
                name=RedditTools.GET_SUBREDDIT_NEW_POSTS.value,
                description="Get new posts from a specific subreddit",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit (e.g. 'Python', 'news')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of posts to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["subreddit_name"]
                }
            ),
            Tool(
                name=RedditTools.GET_SUBREDDIT_TOP_POSTS.value,
                description="Get top posts from a specific subreddit",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit (e.g. 'Python', 'news')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of posts to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        },
                        "time": {
                            "type": "string",
                            "description": "Time filter for top posts (e.g. 'hour', 'day', 'week', 'month', 'year', 'all')",
                            "default": "all",
                            "enum": ["hour", "day", "week", "month", "year", "all"]
                        }
                    },
                    "required": ["subreddit_name"]
                }
            ),
            Tool(
                name=RedditTools.GET_SUBREDDIT_RISING_POSTS.value,
                description="Get rising posts from a specific subreddit",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit (e.g. 'Python', 'news')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of posts to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["subreddit_name"]
                }
            ),
            Tool(
                name=RedditTools.GET_POST_CONTENT.value,
                description="Get detailed content of a specific post",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "post_id": {
                            "type": "string",
                            "description": "ID of the post",
                        },
                        "comment_limit": {
                            "type": "integer",
                            "description": "Number of top-level comments to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        },
                        "comment_depth": {
                            "type": "integer",
                            "description": "Maximum depth of comment tree (default: 3)",
                            "default": 3,
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["post_id"]
                }
            ),
            Tool(
                name=RedditTools.GET_POST_COMMENTS.value,
                description="Get comments from a post",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "post_id": {
                            "type": "string",
                            "description": "ID of the post",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of comments to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["post_id"]
                }
            ),
            Tool(
                name=RedditTools.SEARCH_REDDIT.value,
                description="Search across all of Reddit for posts matching a query",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "sort": {
                            "type": "string",
                            "description": "Sort order",
                            "enum": ["relevance", "new", "hot", "top", "comments"],
                            "default": "relevance"
                        },
                        "time": {
                            "type": "string", 
                            "description": "Time filter",
                            "enum": ["hour", "day", "week", "month", "year", "all"],
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name=RedditTools.SEARCH_SUBREDDIT.value,
                description="Search within a specific subreddit for posts matching a query",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subreddit_name": {
                            "type": "string",
                            "description": "Name of the subreddit to search (e.g. 'Python', 'news')"
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "sort": {
                            "type": "string",
                            "description": "Sort order",
                            "enum": ["relevance", "new", "hot", "top", "comments"],
                            "default": "relevance"
                        },
                        "time": {
                            "type": "string",
                            "description": "Time filter",
                            "enum": ["hour", "day", "week", "month", "year", "all"],
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 10
                        }
                    },
                    "required": ["subreddit_name", "query"]
                }
            ),
            Tool(
                name=RedditTools.SEARCH_SUBREDDITS.value,
                description="Search for subreddits by name or description",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for subreddit names or descriptions"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 50)",
                            "minimum": 1,
                            "maximum": 50,
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name=RedditTools.SEARCH_USER_POSTS.value,
                description="Search through a user's post history",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "Reddit username to search"
                        },
                        "sort": {
                            "type": "string",
                            "description": "Sort order",
                            "enum": ["new", "hot", "top"],
                            "default": "new"
                        },
                        "time": {
                            "type": "string",
                            "description": "Time filter for 'top' sort",
                            "enum": ["hour", "day", "week", "month", "year", "all"],
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 10
                        }
                    },
                    "required": ["username"]
                }
            ),
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool calls for Reddit API."""
        try:
            match name:
                case RedditTools.GET_FRONTPAGE_POSTS.value:
                    limit = arguments.get("limit", 10)
                    result = reddit_server.get_frontpage_posts(limit)

                case RedditTools.GET_SUBREDDIT_INFO.value:
                    subreddit_name = arguments.get("subreddit_name")
                    if not subreddit_name:
                        raise ValueError("Missing required argument: subreddit_name")
                    result = reddit_server.get_subreddit_info(subreddit_name)

                case RedditTools.GET_SUBREDDIT_HOT_POSTS.value:
                    subreddit_name = arguments.get("subreddit_name")
                    if not subreddit_name:
                        raise ValueError("Missing required argument: subreddit_name")
                    limit = arguments.get("limit", 10)
                    result = reddit_server.get_subreddit_hot_posts(subreddit_name, limit)

                case RedditTools.GET_SUBREDDIT_NEW_POSTS.value:
                    subreddit_name = arguments.get("subreddit_name")
                    if not subreddit_name:
                        raise ValueError("Missing required argument: subreddit_name")
                    limit = arguments.get("limit", 10)
                    result = reddit_server.get_subreddit_new_posts(subreddit_name, limit)

                case RedditTools.GET_SUBREDDIT_TOP_POSTS.value:
                    subreddit_name = arguments.get("subreddit_name")
                    if not subreddit_name:
                        raise ValueError("Missing required argument: subreddit_name")
                    limit = arguments.get("limit", 10)
                    time = arguments.get("time", "all")
                    result = reddit_server.get_subreddit_top_posts(subreddit_name, limit, time)

                case RedditTools.GET_SUBREDDIT_RISING_POSTS.value:
                    subreddit_name = arguments.get("subreddit_name")
                    if not subreddit_name:
                        raise ValueError("Missing required argument: subreddit_name")
                    limit = arguments.get("limit", 10)
                    result = reddit_server.get_subreddit_rising_posts(subreddit_name, limit)

                case RedditTools.GET_POST_CONTENT.value:
                    post_id = arguments.get("post_id")
                    if not post_id:
                        raise ValueError("Missing required argument: post_id")
                    comment_limit = arguments.get("comment_limit", 10)
                    comment_depth = arguments.get("comment_depth", 3)
                    result = reddit_server.get_post_content(post_id, comment_limit, comment_depth)

                case RedditTools.GET_POST_COMMENTS.value:
                    post_id = arguments.get("post_id")
                    if not post_id:
                        raise ValueError("Missing required argument: post_id")
                    limit = arguments.get("limit", 10)
                    result = reddit_server.get_post_comments(post_id, limit)

                case RedditTools.SEARCH_REDDIT.value:
                    query = arguments.get("query")
                    if not query:
                        raise ValueError("Missing required argument: query")
                    sort = arguments.get("sort", "relevance")
                    time = arguments.get("time", "all")
                    limit = min(int(arguments.get("limit", 10)), 100)
                    result = reddit_server.search_reddit(query, sort, time, limit)

                case RedditTools.SEARCH_SUBREDDIT.value:
                    subreddit_name = arguments.get("subreddit_name")
                    query = arguments.get("query")
                    if not subreddit_name or not query:
                        raise ValueError("Missing required arguments: subreddit_name and query")
                    sort = arguments.get("sort", "relevance")
                    time = arguments.get("time", "all")
                    limit = min(int(arguments.get("limit", 10)), 100)
                    result = reddit_server.search_subreddit(subreddit_name, query, sort, time, limit)

                case RedditTools.SEARCH_SUBREDDITS.value:
                    query = arguments.get("query")
                    if not query:
                        raise ValueError("Missing required argument: query")
                    limit = min(int(arguments.get("limit", 10)), 50)
                    result = reddit_server.search_subreddits(query, limit)

                case RedditTools.SEARCH_USER_POSTS.value:
                    username = arguments.get("username")
                    if not username:
                        raise ValueError("Missing required argument: username")
                    sort = arguments.get("sort", "new")
                    time = arguments.get("time", "all")
                    limit = min(int(arguments.get("limit", 10)), 100)
                    result = reddit_server.search_user_posts(username, sort, time, limit)

                case _:
                    raise ValueError(f"Unknown tool: {name}")

            return [
                TextContent(type="text", text=json.dumps(result, default=lambda x: x.model_dump(), indent=2))
            ]

        except Exception as e:
            raise ValueError(f"Error processing mcp-server-reddit query: {str(e)}")

    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)