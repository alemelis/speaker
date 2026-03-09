## Pain points

- when tapping a tag on the reader, it takes ~2s for playback to start. This is possibly due to the sequence of requests done: query -> pick first -> clear queue -> enqueue -> play

## What I want

- The first query is done to avoid the need for manually typing the full title for each tag. Now that we have a db and the tag-editor, we can rewrite all the tag values so that we have perfect match without the query. 
- Clearing queue is not needed. We just need to add at the end and start playing from there
- bring tap -> playback within the sub-second mark

## Discussion

A few suspects in order of likely impact:

1. AirPlay buffering — the biggest one. AirPlay maintains a ~2s buffer for multi-room sync by design. This is
protocol-level and unavoidable regardless of how fast our code is. Everything before the sound comes out is dominated by
this.
2. time.sleep(0.05) in the main loop — adds up to 50ms of extra lag between tag read and read_tag() being called. Minor
but free to remove:

while True:
    try:
        tag_id = next(tag_gen)
        ...
    except StopIteration:
        pass
    # remove the sleep

3. owntone expression search — still does an internal library scan. Not much we can do here short of using a URI
directly.
