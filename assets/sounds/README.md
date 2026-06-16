# Custom result sounds

Drop your own audio files here to replace the built-in synthesized sounds.

| When                | File name (any one extension) |
|---------------------|-------------------------------|
| **Correct answer**  | `correct.mp3` (or `.wav` / `.ogg` / `.m4a` / `.aac`) |
| **Wrong answer**    | `wrong.mp3`   (or `.wav` / `.ogg` / `.m4a` / `.aac`) |

- Keep them short (1–3 seconds) and reasonably small (< ~500 KB) so they load fast.
- If a file is missing, the app falls back to the synthesized "ta-da" / "sad trombone".
- The "🔊 Sound & animation" sidebar toggle still mutes everything.

⚠️ Only add audio you have the right to use. Don't commit copyrighted clips
(e.g. ripped from YouTube) to a public repository.

After adding the files: `git add assets/sounds && git commit && git push`, then
reboot the app on Streamlit Cloud.
