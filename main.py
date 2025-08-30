#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import time
import logging
import threading
import re
import tempfile
import os
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_bale_forwarder.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TelegramChannelBaleForwarder:
    def __init__(self):
        # Load configuration from environment variables
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.bale_token = os.getenv('BALE_BOT_TOKEN')
        self.bale_chat_id = os.getenv('BALE_CHAT_ID')
        self.source_channel = os.getenv('SOURCE_CHANNEL')  # Default to your channel
        
        # Validate required environment variables
        if not all([self.telegram_token, self.bale_token, self.bale_chat_id]):
            raise ValueError("Missing required environment variables. Check your .env file.")
        
        # API URLs
        self.telegram_base_url = f"https://api.telegram.org/bot{self.telegram_token}"
        self.bale_base_url = f"https://tapi.bale.ai/bot{self.bale_token}"
        
        # Bot state
        self.last_update_id = 0
        self.running = False
        self.media_groups = defaultdict(list)
        self.media_group_timeout = 5
        self.source_channel_id = None  # Will be resolved from username

    def resolve_channel_id(self) -> Optional[int]:
        """Resolve channel username to chat ID"""
        try:
            response = requests.post(
                f"{self.telegram_base_url}/getChat",
                json={'chat_id': self.source_channel},
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            result = response.json()
            if result.get('ok'):
                chat_info = result.get('result', {})
                chat_id = chat_info.get('id')
                chat_title = chat_info.get('title', 'Unknown')
                chat_type = chat_info.get('type', 'Unknown')
                
                logger.info(f"Source channel resolved: {chat_title} (ID: {chat_id}, Type: {chat_type})")
                return chat_id
            else:
                error_description = result.get('description', 'Unknown error')
                logger.error(f"Failed to resolve channel: {error_description}")
                return None
                
        except Exception as e:
            logger.error(f"Error resolving channel ID: {e}")
            return None

    def get_telegram_updates(self) -> List[Dict]:
        """Get updates from Telegram bot API and filter for source channel"""
        try:
            params = {
                'offset': self.last_update_id + 1,
                'timeout': 30,
                'limit': 100
            }
            
            response = requests.get(
                f"{self.telegram_base_url}/getUpdates",
                params=params,
                timeout=35
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get('ok') and data.get('result'):
                # Filter updates to include both messages and channel posts from our source channel
                filtered_updates = []
                for update in data['result']:
                    # Check for both regular messages and channel posts
                    message = None
                    if 'message' in update:
                        message = update['message']
                        message_type = "message"
                    elif 'channel_post' in update:
                        message = update['channel_post']
                        message_type = "channel_post"
                        # Convert channel_post to message format for processing
                        update['message'] = message
                    
                    if message:
                        chat = message.get('chat', {})
                        chat_id = chat.get('id')
                        
                        # Check if message is from our source channel
                        if chat_id == self.source_channel_id:
                            filtered_updates.append(update)
                            logger.info(f"New {message_type} from source channel: {message.get('message_id')}")
                        else:
                            logger.debug(f"Ignoring message from other chat: {chat_id}")
                
                return filtered_updates
            return []
            
        except Exception as e:
            logger.error(f"Error getting Telegram updates: {e}")
            return []

    def download_telegram_file(self, file_id: str) -> Optional[bytes]:
        """Download file from Telegram"""
        try:
            response = requests.get(
                f"{self.telegram_base_url}/getFile",
                params={'file_id': file_id},
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get('ok'):
                return None
                
            file_path = data['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{self.telegram_token}/{file_path}"
            
            response = requests.get(file_url, timeout=60)
            response.raise_for_status()
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None

    def utf16_to_utf8_offset(self, text: str, utf16_offset: int) -> int:
        """Convert UTF-16 offset to UTF-8 offset for proper text extraction"""
        try:
            utf16_encoded = text.encode('utf-16le')
            byte_offset = utf16_offset * 2
            
            if byte_offset > len(utf16_encoded):
                return len(text)
            
            utf16_substring = utf16_encoded[:byte_offset]
            utf8_substring = utf16_substring.decode('utf-16le', errors='ignore')
            
            return len(utf8_substring)
        except:
            return min(utf16_offset, len(text))

    def extract_links_from_entities(self, text: str, entities: List[Dict]) -> List[Tuple[str, str]]:
        """Extract all text links with proper UTF-16 to UTF-8 conversion"""
        links = []
        
        # Filter and sort link entities
        link_entities = [e for e in entities if e['type'] in ['text_link', 'url', 'mention']]
        link_entities.sort(key=lambda x: x['offset'])
        
        for entity in link_entities:
            utf16_start = entity['offset']
            utf16_length = entity['length']
            
            # Convert UTF-16 offsets to UTF-8
            utf8_start = self.utf16_to_utf8_offset(text, utf16_start)
            utf8_end = self.utf16_to_utf8_offset(text, utf16_start + utf16_length)
            
            # Extract text
            entity_text = text[utf8_start:utf8_end].strip()
            
            # Handle different entity types
            if entity['type'] == 'text_link':
                url = entity.get('url', '')
                if entity_text and url:
                    links.append((entity_text, url))
            elif entity['type'] == 'url':
                if entity_text:
                    links.append((entity_text, entity_text))
            elif entity['type'] == 'mention':
                if entity_text.startswith('@'):
                    username = entity_text[1:]
                    url = f"https://t.me/{username}"
                    links.append((entity_text, url))
        
        return links

    def clean_text_for_bale(self, text: str) -> str:
        """Clean text for Bale by removing problematic characters and formatting"""
        # Remove zero-width characters
        clean_text = re.sub(r'[\u200c\u200d\u200e\u200f\ufeff]', '', text)
        
        # Clean up whitespace while preserving structure
        lines = clean_text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            cleaned_line = re.sub(r'[ \t]+', ' ', line.strip())
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
            elif len(cleaned_lines) > 0 and cleaned_lines[-1]:
                cleaned_lines.append('')
        
        return '\n'.join(cleaned_lines)

    def format_message_for_bale(self, text: str, links: List[Tuple[str, str]]) -> str:
        """Format message with inline links replacing the original link text"""
        clean_text = self.clean_text_for_bale(text)
        
        if not links:
            return clean_text
        
        # Replace each link text in the clean text with markdown link
        formatted_text = clean_text
        
        # Sort links by text length (longest first) to avoid partial replacements
        sorted_links = sorted(links, key=lambda x: len(x[0]), reverse=True)
        
        for link_text, link_url in sorted_links:
            if link_text in formatted_text:
                # Add spaces around markdown link to avoid emoji conflicts
                markdown_link = f" [{link_text}]({link_url}) "
                # Replace first occurrence to avoid duplicates
                formatted_text = formatted_text.replace(link_text, markdown_link, 1)
        
        # Clean up excessive spaces
        formatted_text = re.sub(r' {3,}', '  ', formatted_text)  # Max 2 spaces
        formatted_text = re.sub(r' +\|', ' |', formatted_text)   # Clean | separators
        formatted_text = re.sub(r'\| +', '| ', formatted_text)   # Clean | separators
        
        return formatted_text

    def extract_inline_keyboard(self, reply_markup: Dict) -> Optional[Dict]:
        """Extract and convert Telegram inline keyboard to Bale format"""
        if not reply_markup or 'inline_keyboard' not in reply_markup:
            return None
        
        try:
            telegram_keyboard = reply_markup['inline_keyboard']
            bale_keyboard = []
            
            for row in telegram_keyboard:
                bale_row = []
                for button in row:
                    if 'text' in button and 'url' in button:
                        bale_button = {
                            'text': button['text'],
                            'url': button['url']
                        }
                        bale_row.append(bale_button)
                
                if bale_row:  # Only add non-empty rows
                    bale_keyboard.append(bale_row)
            
            if bale_keyboard:
                return {'inline_keyboard': bale_keyboard}
            
        except Exception as e:
            logger.error(f"Error processing inline keyboard: {e}")
        
        return None

    def send_to_bale(self, text: str, parse_mode: str = 'Markdown', reply_markup: Optional[Dict] = None) -> bool:
        """Send message to Bale with optional inline keyboard"""
        try:
            data = {
                'chat_id': self.bale_chat_id,
                'text': text,
                'parse_mode': parse_mode
            }
            
            # Add inline keyboard if provided
            if reply_markup:
                data['reply_markup'] = reply_markup
            
            headers = {'Content-Type': 'application/json'}
            
            response = requests.post(
                f"{self.bale_base_url}/sendMessage",
                json=data,
                headers=headers,
                timeout=30
            )
            
            result = response.json()
            success = result.get('ok', False)
            
            if not success:
                error_description = result.get('description', 'Unknown error')
                logger.error(f"Bale API error: {error_description}")
                
                # Try without markdown if parsing failed
                if 'parse' in error_description.lower() or 'markdown' in error_description.lower():
                    logger.info("Retrying without markdown parsing")
                    data['parse_mode'] = None
                    response = requests.post(
                        f"{self.bale_base_url}/sendMessage",
                        json=data,
                        headers=headers,
                        timeout=30
                    )
                    result = response.json()
                    success = result.get('ok', False)
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending to Bale: {e}")
            return False

    def send_media_group_to_bale(self, photos: List[bytes], caption: str, reply_markup: Optional[Dict] = None) -> bool:
        """Send media to Bale with proper keyboard handling"""
        if not photos:
            return False
        
        # If there's only one photo or we need keyboard, send as single photo
        if len(photos) == 1 or reply_markup:
            return self.send_single_photo_to_bale(photos[0], caption, reply_markup)
        
        # Multiple photos without keyboard - send as media group
        temp_files = []
        try:
            for i, photo_data in enumerate(photos):
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                temp_file.write(photo_data)
                temp_file.close()
                temp_files.append(temp_file.name)
            
            # Prepare media list
            media_list = []
            files = {}
            
            for i, temp_file_path in enumerate(temp_files):
                media_item = {
                    'type': 'photo',
                    'media': f"attach://photo_{i+1}"
                }
                
                # Add caption only to first photo
                if i == 0 and caption:
                    media_item['caption'] = caption
                    media_item['parse_mode'] = 'Markdown'
                
                media_list.append(media_item)
                
                # Add file to files dict
                with open(temp_file_path, 'rb') as f:
                    files[f'photo_{i+1}'] = (f'photo_{i+1}.jpg', f.read())
            
            # Send media group
            data = {
                'chat_id': self.bale_chat_id,
                'media': json.dumps(media_list)
            }
            
            response = requests.post(
                f"{self.bale_base_url}/sendMediaGroup",
                data=data,
                files=files,
                timeout=60
            )
            
            result = response.json()
            success = result.get('ok', False)
            
            if not success:
                error_description = result.get('description', 'Unknown error')
                logger.error(f"Bale media group send error: {error_description}")
                
                # Retry with plain caption if markdown failed
                if caption and ('parse' in error_description.lower() or 'markdown' in error_description.lower()):
                    logger.info("Retrying media group with plain text caption")
                    for item in media_list:
                        if 'parse_mode' in item:
                            del item['parse_mode']
                    
                    data['media'] = json.dumps(media_list)
                    response = requests.post(
                        f"{self.bale_base_url}/sendMediaGroup",
                        data=data,
                        files=files,
                        timeout=60
                    )
                    result = response.json()
                    success = result.get('ok', False)
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending media group to Bale: {e}")
            return False
        finally:
            # Clean up temporary files
            for temp_file_path in temp_files:
                try:
                    os.unlink(temp_file_path)
                except:
                    pass

    def send_single_photo_to_bale(self, photo_data: bytes, caption: str, reply_markup: Optional[Dict] = None) -> bool:
        """Send single photo to Bale with inline keyboard support"""
        temp_file = None
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            temp_file.write(photo_data)
            temp_file.close()
            
            # Prepare data
            data = {
                'chat_id': self.bale_chat_id,
            }
            
            if caption:
                data['caption'] = caption
                data['parse_mode'] = 'Markdown'
            
            # Add inline keyboard if provided
            if reply_markup:
                data['reply_markup'] = json.dumps(reply_markup)
            
            # Send photo
            with open(temp_file.name, 'rb') as f:
                files = {'photo': ('photo.jpg', f.read())}
            
            response = requests.post(
                f"{self.bale_base_url}/sendPhoto",
                data=data,
                files=files,
                timeout=60
            )
            
            result = response.json()
            success = result.get('ok', False)
            
            if not success:
                error_description = result.get('description', 'Unknown error')
                logger.error(f"Bale photo send error: {error_description}")
                
                # Retry without markdown if parsing failed
                if caption and ('parse' in error_description.lower() or 'markdown' in error_description.lower()):
                    logger.info("Retrying photo with plain text caption")
                    data['parse_mode'] = None
                    with open(temp_file.name, 'rb') as f:
                        files = {'photo': ('photo.jpg', f.read())}
                    
                    response = requests.post(
                        f"{self.bale_base_url}/sendPhoto",
                        data=data,
                        files=files,
                        timeout=60
                    )
                    result = response.json()
                    success = result.get('ok', False)
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending photo to Bale: {e}")
            return False
        finally:
            # Clean up temporary file
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    def process_media_group(self, group_id: str):
        """Process media group messages"""
        messages = self.media_groups.pop(group_id, [])
        if not messages:
            return
        
        logger.info(f"Processing media group with {len(messages)} items from channel")
        
        # Get caption, entities and reply_markup from first message
        first_msg = messages[0]
        caption = first_msg.get('caption', '')
        entities = first_msg.get('caption_entities', [])
        reply_markup = first_msg.get('reply_markup')
        
        # Download all photos
        photos = []
        for msg in messages:
            if 'photo' in msg:
                largest_photo = max(msg['photo'], key=lambda x: x.get('file_size', 0))
                photo_data = self.download_telegram_file(largest_photo['file_id'])
                if photo_data:
                    photos.append(photo_data)
        
        if not photos:
            logger.warning("No photos could be downloaded from media group")
            return
        
        # Extract links and format caption
        links = self.extract_links_from_entities(caption, entities)
        formatted_caption = self.format_message_for_bale(caption, links)
        
        # Extract inline keyboard
        bale_keyboard = self.extract_inline_keyboard(reply_markup) if reply_markup else None
        
        # Log activity
        keyboard_info = f", {len(bale_keyboard['inline_keyboard'])} keyboard rows" if bale_keyboard else ""
        logger.info(f"Forwarding media group: {len(photos)} photos, {len(links)} links{keyboard_info}")
        
        # Send to Bale
        success = self.send_media_group_to_bale(photos, formatted_caption, bale_keyboard)
        
        if success:
            logger.info("Media group forwarded successfully")
        else:
            logger.error("Failed to forward media group")

    def process_single_message(self, message: Dict):
        """Process single message (text or photo)"""
        try:
            if 'text' in message:
                # Text message
                text = message['text']
                entities = message.get('entities', [])
                reply_markup = message.get('reply_markup')
                
                # Extract links and format
                links = self.extract_links_from_entities(text, entities)
                formatted_text = self.format_message_for_bale(text, links)
                
                # Extract inline keyboard
                bale_keyboard = self.extract_inline_keyboard(reply_markup) if reply_markup else None
                
                # Log activity
                keyboard_info = f", {len(bale_keyboard['inline_keyboard'])} keyboard rows" if bale_keyboard else ""
                logger.info(f"Forwarding text message: {len(links)} links{keyboard_info}")
                
                # Send to Bale
                success = self.send_to_bale(formatted_text, reply_markup=bale_keyboard)
                
                if success:
                    logger.info("Text message forwarded successfully")
                else:
                    logger.error("Failed to forward text message")
                    
            elif 'photo' in message:
                # Single photo
                caption = message.get('caption', '')
                entities = message.get('caption_entities', [])
                reply_markup = message.get('reply_markup')
                
                # Download photo
                largest_photo = max(message['photo'], key=lambda x: x.get('file_size', 0))
                photo_data = self.download_telegram_file(largest_photo['file_id'])
                
                if photo_data:
                    # Extract links and format caption
                    links = self.extract_links_from_entities(caption, entities)
                    formatted_caption = self.format_message_for_bale(caption, links)
                    
                    # Extract inline keyboard
                    bale_keyboard = self.extract_inline_keyboard(reply_markup) if reply_markup else None
                    
                    # Log activity
                    keyboard_info = f", {len(bale_keyboard['inline_keyboard'])} keyboard rows" if bale_keyboard else ""
                    logger.info(f"Forwarding single photo: {len(links)} links{keyboard_info}")
                    
                    # Send to Bale
                    success = self.send_media_group_to_bale([photo_data], formatted_caption, bale_keyboard)
                    
                    if success:
                        logger.info("Single photo forwarded successfully")
                    else:
                        logger.error("Failed to forward single photo")
                else:
                    logger.error("Failed to download photo")
                        
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def process_telegram_update(self, update: Dict):
        """Process incoming Telegram update"""
        if 'message' not in update:
            return
        
        message = update['message']
        
        # Handle media groups
        if 'media_group_id' in message:
            group_id = message['media_group_id']
            self.media_groups[group_id].append(message)
            
            # Set timer to process media group
            threading.Timer(self.media_group_timeout, self.process_media_group, args=(group_id,)).start()
        else:
            # Handle single messages
            threading.Thread(
                target=self.process_single_message,
                args=(message,),
                daemon=True
            ).start()

    def start_polling(self):
        """Start polling for updates"""
        logger.info(f"Starting to monitor channel: {self.source_channel}")
        self.running = True
        
        while self.running:
            try:
                updates = self.get_telegram_updates()
                
                for update in updates:
                    self.last_update_id = update['update_id']
                    self.process_telegram_update(update)
                
                if not updates:
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                logger.info("Stopping bot...")
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(5)
        
        self.running = False

    def run(self):
        """Main run method"""
        logger.info("Telegram Channel to Bale Forwarder v1.0")
        logger.info("Testing API connections...")
        
        try:
            # Test Telegram connection
            telegram_response = requests.get(f"{self.telegram_base_url}/getMe", timeout=10)
            if telegram_response.json().get('ok'):
                telegram_bot_info = telegram_response.json().get('result', {})
                bot_name = telegram_bot_info.get('first_name', 'Unknown')
                logger.info(f"Telegram API: Connected ({bot_name})")
            else:
                logger.error("Telegram API: Failed to connect")
                return
            
            # Resolve source channel ID
            logger.info(f"Resolving source channel: {self.source_channel}")
            self.source_channel_id = self.resolve_channel_id()
            if not self.source_channel_id:
                logger.error("Failed to resolve source channel. Make sure the bot is admin in the channel.")
                return
            
            # Test Bale connection
            bale_response = requests.get(f"{self.bale_base_url}/getMe", timeout=10)
            if bale_response.json().get('ok'):
                logger.info("Bale API: Connected")
            else:
                logger.error("Bale API: Failed to connect")
                return
            
            logger.info(f"Source channel: {self.source_channel} (ID: {self.source_channel_id})")
            logger.info(f"Target chat: {self.bale_chat_id}")
            logger.info("Bot ready to monitor channel and forward posts")
            logger.info("Press Ctrl+C to stop")
            
            self.start_polling()
                
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")


if __name__ == "__main__":
    try:
        forwarder = TelegramChannelBaleForwarder()
        forwarder.run()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print("\nPlease create a .env file with the following variables:")
        print("TELEGRAM_BOT_TOKEN=your_telegram_bot_token")
        print("BALE_BOT_TOKEN=your_bale_bot_token") 
        print("BALE_CHAT_ID=@your_bale_channel")
        print("SOURCE_CHANNEL=@your_telegram_channel")
