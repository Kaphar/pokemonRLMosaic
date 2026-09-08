import struct
from typing import List, Dict, Optional, Any


PLAYER_NAME_ADDRESS = 0xD158
BADGES_ADDRESS = 0xD356
MONEY_ADDRESS = 0xD347
COINS_ADDRESS = 0xD37D
BAG_COUNT_ADDRESS = 0xD31D
BAG_ITEMS_ADDRESS = 0xD31E

class MemoryReader:
    """Mock MemoryReader class - replace with actual implementation"""
    is_initialized = False
    current_game = None

class GameUtils:
    """Utility functions for reading game memory"""
    
    @staticmethod
    def read_bytes(address: int, length: int, domain: str = "System Bus") -> List[int]:
        """Read bytes from memory - implement based on your memory reading method"""
        # Replace with actual memory reading implementation
        return [0] * length
    
    @staticmethod
    def read8(address: int, domain: str = "System Bus") -> int:
        """Read 8-bit value from memory"""
        data = GameUtils.read_bytes(address, 1, domain)
        return data[0] if data else 0
    
    @staticmethod
    def read16(address: int, domain: str = "System Bus") -> int:
        """Read 16-bit value from memory (little-endian)"""
        data = GameUtils.read_bytes(address, 2, domain)
        if len(data) >= 2:
            return struct.unpack('<H', bytes(data[:2]))[0]
        return 0
    
    @staticmethod
    def bcd_to_decimal(bcd_bytes: List[int]) -> int:
        """Convert BCD encoded bytes to decimal integer"""
        result = 0
        for byte in bcd_bytes:
            result = result * 100 + ((byte >> 4) * 10 + (byte & 0x0F))
        return result

class Charmaps:
    """Character map for decrypting text"""
    
    @staticmethod
    def decrypt_text(data: List[int], charset: str = "GB") -> str:
        """Decrypt text from game memory - implement based on your charmap"""
        # Replace with actual character mapping
        return ''.join(chr(b) if 32 <= b <= 126 else '?' for b in data).strip('\0')

class PokemonData:
    """Pokemon data utilities"""
    
    @staticmethod
    def get_item_name(item_id: int) -> str:
        """Get item name by ID - implement based on your item database"""
        # Replace with actual item name lookup
        item_names = {
            0: "Nothing",
            1: "Master Ball",
            2: "Ultra Ball",
            3: "Great Ball",
            4: "Poké Ball",
            5: "Town Map",
            6: "Bicycle",
            7: "Pokédex",
            # Add more items as needed
        }
        return item_names.get(item_id, f"Unknown Item ({item_id})")

class Gen1PlayerReader:
    """Gen 1 Pokemon player reader"""
    
    def __init__(self, memory_reader=None):
        self.trainer_info = None
        self.bag = {"items": []}
        self.memory_reader = memory_reader

    def _read_bytes(self, address: int, length: int, domain: str = "System Bus") -> List[int]:
        if self.memory_reader is not None:
            return [self.memory_reader.read_byte(address + offset) for offset in range(length)]
        return GameUtils.read_bytes(address, length, domain)

    def _read8(self, address: int, domain: str = "System Bus") -> int:
        return self._read_bytes(address, 1, domain)[0]

    def _read16(self, address: int, domain: str = "System Bus") -> int:
        data = self._read_bytes(address, 2, domain)
        return struct.unpack('<H', bytes(data[:2]))[0] if len(data) >= 2 else 0
    
    def update_trainer_info(self) -> None:
        """Update trainer information from memory"""
        if self.memory_reader is None and (not MemoryReader.is_initialized or not MemoryReader.current_game):
            print("MemoryReader not initialized or no game loaded")
            return
        
        game_data = MemoryReader.current_game
        if self.memory_reader is None and (not game_data or 'trainer_offsets' not in game_data):
            print("No game data or trainer offsets found")
            return
        
        domain = "System Bus"
        
        # Trainer Name (11 bytes)
        offsets = game_data.get('trainer_offsets', {}) if game_data else {}
        name_addr = offsets.get('name', PLAYER_NAME_ADDRESS)
        name_data = self._read_bytes(name_addr, 11, domain)
        name = Charmaps.decrypt_text(name_data, "GB")
        
        # Badges (1 byte, 1 bit per badge)
        badges_addr = offsets.get('badges', BADGES_ADDRESS)
        badges = self._read8(badges_addr, domain)
        
        badge_list = [
            {"badge_num": 1, "name": "Boulder Badge", "earned": bool(badges & 0x01)},
            {"badge_num": 2, "name": "Cascade Badge", "earned": bool(badges & 0x02)},
            {"badge_num": 3, "name": "Thunder Badge", "earned": bool(badges & 0x04)},
            {"badge_num": 4, "name": "Rainbow Badge", "earned": bool(badges & 0x08)},
            {"badge_num": 5, "name": "Soul Badge", "earned": bool(badges & 0x10)},
            {"badge_num": 6, "name": "Marsh Badge", "earned": bool(badges & 0x20)},
            {"badge_num": 7, "name": "Volcano Badge", "earned": bool(badges & 0x40)},
            {"badge_num": 8, "name": "Earth Badge", "earned": bool(badges & 0x80)}
        ]
        
        # Money (3 bytes, BCD encoded)
        money_addr = offsets.get('money', MONEY_ADDRESS)
        money_bcd = self._read_bytes(money_addr, 3, domain)
        money = GameUtils.bcd_to_decimal(money_bcd)
        
        # Coins (2 bytes, binary encoded)
        coins_addr = offsets.get('coins', COINS_ADDRESS)
        coins = self._read16(coins_addr, domain)
        
        self.trainer_info = {
            "name": name,
            "badges": badge_list,
            "badge_count": sum(badge["earned"] for badge in badge_list),
            "money": money,
            "coins": coins or 0
        }
        return self.trainer_info
    
    def read_bag(self) -> Dict[str, Any]:
        """Read bag items from memory"""
        self.update_trainer_info()
        game_data = MemoryReader.current_game
        
        if not self.trainer_info:
            print("No trainer info available, cannot read bag")
            return {}
        elif self.memory_reader is None and (not game_data or 'trainer_offsets' not in game_data):
            print("No game data or trainer offsets found")
            return {}
        
        domain = "System Bus"
        
        # Bag count (1 byte)
        offsets = game_data.get('trainer_offsets', {}) if game_data else {}
        bag_count = min(self._read8(offsets.get('bag_count', BAG_COUNT_ADDRESS), domain), 40)
        bag = []
        
        # Bag is max 40 items, each being 2 bytes (item ID and quantity)
        bag_start_addr = offsets.get('bag_items', BAG_ITEMS_ADDRESS)
        for i in range(bag_count):
            item_addr = bag_start_addr + (i * 2)
            item_data = self._read_bytes(item_addr, 2, domain)
            
            item = {
                "id": item_data[0],
                "quantity": item_data[1],
                "name": PokemonData.get_item_name(item_data[0])
            }
            
            if item["id"] == 0:
                break
            
            bag.append(item)
        
        self.bag["items"] = bag
        return self.bag

# Example usage
if __name__ == "__main__":
    # Initialize MemoryReader with your game data
    MemoryReader.is_initialized = True
    MemoryReader.current_game = {
        'trainer_offsets': {
            'name': 0x2598,      # Example offset - replace with actual
            'badges': 0x2602,    # Example offset - replace with actual
            'money': 0x25F3,     # Example offset - replace with actual
            'coins': 0x25F6,     # Example offset - replace with actual
            'bag_count': 0x25C9, # Example offset - replace with actual
            'bag_items': 0x25CB  # Example offset - replace with actual
        }
    }
    
    # Create reader and read bag
    reader = Gen1PlayerReader()
    bag_data = reader.read_bag()
    
    # Display bag contents
    if bag_data and 'items' in bag_data:
        print(f"Bag items ({len(bag_data['items'])}):")
        for item in bag_data['items']:
            print(f"  {item['name']} x{item['quantity']} (ID: {item['id']})")
    
    # Display trainer info
    if reader.trainer_info:
        print(f"\nTrainer: {reader.trainer_info['name']}")
        print(f"Money: {reader.trainer_info['money']}")
        print(f"Coins: {reader.trainer_info['coins']}")
        earned_badges = [b['name'] for b in reader.trainer_info['badges'] if b['earned']]
        print(f"Badges: {', '.join(earned_badges) if earned_badges else 'None'}")