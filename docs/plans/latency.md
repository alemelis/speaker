## Pain points

- when tapping a tag on the reader, it takes ~2s for playback to start. This is possibly due to the sequence of requests done: query -> pick first -> clear queue -> enqueue -> play

## What I want

- The first query is done to avoid the need for manually typing the full title for each tag. Now that we have a db and the tag-editor, we can rewrite all the tag values so that we have perfect match without the query. 
- Clearing queue is not needed. We just need to add at the end and start playing from there
- bring tap -> playback within the sub-second mark
