"""Voice I/O — Task A.

    from voice.encoder import ResemblyzerEncoder   # VoiceEncoder
    from voice.stt import ElevenLabsStt            # Stt
    from voice.clone import clone_utterance        # the Act 2 attack rig

There is no TTS: the agent's questions are rendered as text on screen. That
also removes a synthesis call from the live loop, so a question appears the
moment it is chosen.

Nothing is re-exported here on purpose: `app/main.py` imports each concrete
module inside its own `attempt()` block, so a missing `resemblyzer` takes out
the encoder alone and leaves STT live. A re-export would couple them all to
the heaviest import in the package.

`voice.audio` holds the decoding helpers and depends only on numpy — import it
freely from tests and scripts.
"""
