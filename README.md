# jinyoung-skills

Jinyoung's personal agent skills for Claude Code. Each skill lives in its own
folder under [`skills/`](./skills), and the whole repository is also a Claude
Code plugin, so one install gives you every skill.

## Skills

| Skill | What it does |
|---|---|
| [`youtube-subtitle`](./skills/youtube-subtitle/SKILL.md) | Makes timing-synced Korean subtitles (SRT/VTT) for a YouTube video. Whisper transcribes the audio locally, Claude translates it, and an optional Jev review flags suspicious lines. |

## Installation

This repository is `iamapark/skills`. The plugin and the marketplace it contains
are both named `jinyoung-skills`.

### Claude Code plugin (updates through the plugin system)

```bash
claude plugin marketplace add iamapark/skills
claude plugin install jinyoung-skills@jinyoung-skills
```

Plugin skills are invoked with the plugin name as a prefix, for example
`/jinyoung-skills:youtube-subtitle`.

### Copy the files (any agent, manual updates)

```bash
npx skills@latest add iamapark/skills
```

Or clone the repository and copy a skill folder by hand:

```bash
git clone https://github.com/iamapark/skills.git jinyoung-skills
cp -r jinyoung-skills/skills/youtube-subtitle ~/.claude/skills/
```

Pick one method per agent. Installing both gives you the skill twice.

## Requirements for `youtube-subtitle`

- `ffmpeg`
- Python 3.9 or newer (the setup script creates its own virtual environment with just `faster-whisper` and `yt-dlp`, about 260 MB)
- Optional: `TYPESAFE_API_KEY` for the Jev review step, as described in
  [`references/jev-review.md`](./skills/youtube-subtitle/references/jev-review.md).
  Without a key the skill skips the review and builds the subtitles with
  `--skip-review`; the final report says that no review was done.

Setup installs the Python packages once and is instant afterwards. The first
transcription also downloads the Whisper model (for example about 480 MB for
`small.en`).

## Repository layout

```
<repository root>/
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
