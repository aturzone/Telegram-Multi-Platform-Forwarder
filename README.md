# Telegram to Bale Forwarder

A Python bot that automatically forwards messages from Telegram to Bale messenger with support for text formatting, inline links, media groups, and inline keyboards.

## Features

- Forward text messages with proper link formatting
- Forward single photos and media groups
- Support for inline keyboards (buttons)
- Automatic text cleaning and formatting
- UTF-16 to UTF-8 text entity conversion
- Retry mechanisms for failed requests
- Environment variable configuration
- Comprehensive logging

## Requirements

- Python 3.7+
- Telegram Bot Token
- Bale Bot Token
- Target Bale chat/channel ID

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/telegram-bale-forwarder.git
cd telegram-bale-forwarder
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create your configuration file:
```bash
cp .env.example .env
```

4. Edit `.env` file with your bot tokens:
```bash
nano .env
```

## Configuration

Edit the `.env` file with your bot credentials:

```bash
# Telegram Bot Token (get from @BotFather)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Bale Bot Token (get from Bale BotFather)
BALE_BOT_TOKEN=your_bale_bot_token_here

# Bale target chat ID (channel username with @ or chat ID)
BALE_CHAT_ID=@your_bale_channel_or_chat_id
```

## Usage

Run the bot:
```bash
python main.py
```

The bot will:
1. Connect to both Telegram and Bale APIs
2. Start polling for new messages
3. Forward messages with proper formatting
4. Log all activities to `telegram_bale_forwarder.log`

To stop the bot, press `Ctrl+C`.

## How It Works

1. **Message Detection**: Bot polls Telegram API for new messages
2. **Link Processing**: Extracts and formats inline links using UTF-16 entity data
3. **Media Handling**: Downloads photos and forwards them as media groups or single photos
4. **Keyboard Support**: Converts Telegram inline keyboards to Bale format
5. **Text Cleaning**: Removes problematic Unicode characters and formats text
6. **Error Handling**: Retries failed requests and falls back to plain text if markdown fails

## Supported Message Types

- ✅ Text messages with inline links
- ✅ Single photos with captions
- ✅ Media groups (multiple photos)
- ✅ Messages with inline keyboards
- ✅ Mentions (@username)
- ✅ URL entities

## Logging

The bot creates detailed logs in `telegram_bale_forwarder.log` including:
- Connection status
- Message processing details
- Error messages and retry attempts
- Success/failure status for each forward operation

## Troubleshooting

### Bot not receiving messages
- Ensure the Telegram bot token is correct
- Verify the bot is added to the source chat/channel
- Check that the bot has permission to read messages

### Messages not appearing in Bale
- Verify Bale bot token is correct
- Ensure the bot is added to the target Bale chat/channel
- Check chat ID format (@channel_name or numeric ID)

### Link formatting issues
- The bot automatically handles Persian/Arabic text with proper UTF-16 conversion
- Links are converted to Markdown format with proper spacing

## Security Notes

- Keep your `.env` file private and never commit it to version control
- The `.env.example` file is safe to share as it contains no real tokens
- Bot tokens provide full access to your bots - treat them like passwords

## License

This project is licensed under the MIT License - see the LICENSE file for details.
