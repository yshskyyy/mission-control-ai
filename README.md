# Mission Control AI

Mission Control AI is not a chatbot. It is a personal strategic operating system that continuously aligns daily actions with long-term goals through memory, reflection, and AI-driven planning.


## Current Features

- Modular user profile
- RSS technology news collection
- GitHub trend scanning and project architecture analysis
- OpenAI-powered daily planning
- Daily brief saving
- Daily review saving
- Memory continuity from previous reviews
- SQLite history storage and querying

## Tech Stack

- Python
- OpenAI API
- GitHub API
- SQLite (Python standard library)
- feedparser
- dotenv
- local file-based memory

## Usage

```bash
source venv/bin/activate
python main.py morning
python main.py review
python main.py build-tree
python main.py db-init
python main.py history
```

`morning` and `review` save to both readable Markdown files and
`memory_data/mission_control.db`. Run `db-init` once to import existing Markdown
history into SQLite, then use `history` to inspect recent records.

## Environment Variables

```bash
OPENAI_API_KEY=your_openai_api_key
GITHUB_TOKEN=optional_github_token_for_higher_rate_limits
```
