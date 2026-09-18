# ARC RAIDERS Farm Priority Bot V2

This version has automatic item images.

You no longer upload the image yourself.

## Example

Run:

`/farmpriority`

Then enter:

- item: `Herbals`
- needed: `60`
- priority: `VERY HIGH`
- hours: `24`

The bot creates the Discord Forum post, downloads the matching ARC Raiders item image automatically, applies the `Priority Drop` tag, and deletes the post after 24 hours.

## Built-in items

- Herbals → Herbal Bandage image
- Batts → Battery image
- Ducks → Rubber Duck image
- ARC Circ → ARC Circuitry image
- Showstoppers → Showstopper image
- Smokes → Smoke Grenade image
- Power Rods → Power Rod image
- Hatch Key → Raider Hatch Key image
- Survivor MK3 → Looting Mk. 3 (Survivor) image
- Duct Tape
- Light Gun Parts
- Exodus Modules
- Hornet Drivers → Hornet Driver image
- Advanced Electrical → Advanced Electrical Components image
- Heavy Fuze → Heavy Fuze Grenade image

The `item` field uses autocomplete, so start typing and Discord will show matching items.

## Why the images stay current

The bot resolves the current item image through the ARC Raiders Wiki MediaWiki API when the command is used. This means there is no manual image upload required.

Game imagery belongs to its respective rights holder. The ARC Raiders Wiki is only used as the image source.

## Railway update

If you already deployed V1:

1. Replace your old GitHub files with these V2 files.
2. Commit/push to GitHub.
3. Railway should redeploy automatically.
4. Keep your existing Railway Variables:
   - `DISCORD_TOKEN`
   - `GUILD_ID`
   - `FORUM_CHANNEL_ID`
   - `PRIORITY_TAG_NAME=Priority Drop`
   - `DATABASE_PATH=/data/farm_priority.db`
5. Keep the Railway Volume mounted at `/data`.

You do NOT need to create a new bot token.

## Discord permissions

In the Farm Priority Forum channel give the bot:

- View Channel
- Send Messages
- Create Public Threads
- Send Messages in Threads
- Read Message History
- Attach Files
- Embed Links
- Manage Threads
- Use Application Commands

No Message Content Intent is required for these slash commands.

## Commands

### `/farmpriority`

Creates the priority post.

### `/farmpriorityclose`

Use inside a priority thread to remove it early.


## V3 forum-tag fallback

V3 prevents Discord error `40067: A tag is required to create a forum post in this channel`.

The bot now:

1. Tries to use the tag configured by `PRIORITY_TAG_NAME` (normally `Priority Drop`).
2. If that tag does not exist, it automatically uses the first available tag in the Forum channel.
3. If the Forum has no tags at all, the bot returns a clear message telling you to create at least one tag.
