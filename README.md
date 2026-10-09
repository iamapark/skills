# jinyoung-skills

Jinyoung's personal agent skills for Claude Code. Each skill lives in its own
folder under [`skills/`](./skills), and the whole repository is also a Claude
Code plugin, so one install gives you every skill.

## Skills

| Skill | What it does |
|---|---|
| [`youtube-subtitle`](./skills/youtube-subtitle/SKILL.md) | Makes timing-synced Korean subtitles (SRT/VTT) for a YouTube video. Whisper transcribes the audio locally, Claude translates it, and an optional Jev review flags suspicious lines. |

## Installation

Replace `<owner>` with the GitHub account that hosts this repository.

### Claude Code plugin (updates through the plugin system)

```bash
claude plugin marketplace add <owner>/jinyoung-skills
claude plugin install jinyoung-skills@jinyoung-skills
```

Plugin skills are invoked with the plugin name as a prefix, for example
`/jinyoung-skills:youtube-subtitle`.

### Copy the files (any agent, manual updates)

```bash
npx skills@latest add <owner>/jinyoung-skills
```

Or clone the repository and copy a skill folder by hand:

```bash
git clone https://github.com/<owner>/jinyoung-skills.git
cp -r jinyoung-skills/skills/youtube-subtitle ~/.claude/skills/
```

Pick one method per agent. Installing both gives you the skill twice.

## Requirements for `youtube-subtitle`

- `ffmpeg`
- Python 3.12 (the setup script creates its own virtual environment and installs `buzz-captions`)
- `TYPESAFE_API_KEY` for the Jev review step, as described in
  [`references/jev-review.md`](./skills/youtube-subtitle/references/jev-review.md).
  The skill does not treat a run without a completed review as finished.

The first run downloads Python packages and a Whisper model, which takes a few
minutes. After that, setup is instant.

## Repository layout

```
jinyoung-skills/
├── .claude-plugin/
│   ├── marketplace.json   # marketplace listing (one plugin)
│   └── plugin.json        # plugin manifest, lists every skill folder
├── skills/
│   └── <skill-name>/      # SKILL.md plus its scripts, references and tests
├── LICENSE
└── README.md
```

To add a skill, create `skills/<skill-name>/SKILL.md` and add the folder to the
`skills` list in `.claude-plugin/plugin.json`. Then bump `version` there so
plugin users receive the update.

## License

[MIT](./LICENSE)
