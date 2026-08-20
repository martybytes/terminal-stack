<!-- terminal-stack-tts-start -->
## Spoken completion summaries (terminal-stack TTS)

At the very end of your final message each turn, append an HTML comment of
the form `<!-- speak: <summary> -->` where `<summary>` is ONE spoken-style
sentence, 15 words or fewer, describing what you just did or what you need —
plain words only, no code, no paths, no markdown. Examples:

`<!-- speak: Added the retry logic and all tests pass. -->`
`<!-- speak: I need you to choose between the two migration options. -->`

If the turn was trivial (a one-line answer, a simple acknowledgment), omit
the comment entirely. This comment is read aloud by a local notifier and is
invisible in rendered output — never mention it in the message body.
<!-- terminal-stack-tts-end -->
