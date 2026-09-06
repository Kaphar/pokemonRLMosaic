"""
Gen 1 Party Reader - Python adaptation
Reads Pokémon party data from Gen 1 game memory
"""

import struct
from typing import Dict, List, Optional, Tuple, Any


class Gen1PartyReader:
    """Reader for Gen 1 Pokémon party data"""
    
    # Gen1 species list (based on internal species order, not Pokedex order)
    SPECIES_NAMES = [
        "Rhydon", "Kangaskhan", "Nidoran♂", "Clefairy", "Spearow", "Voltorb", "Nidoking", "Slowbro",
        "Ivysaur", "Exeggutor", "Lickitung", "Exeggcute", "Grimer", "Gengar", "Nidoran♀", "Nidoqueen",
        "Cubone", "Rhyhorn", "Lapras", "Arcanine", "Mew", "Gyarados", "Shellder", "Tentacool", "Gastly",
        "Scyther", "Staryu", "Blastoise", "Pinsir", "Tangela", "MissingNo.", "MissingNo.", "Growlithe",
        "Onix", "Fearow", "Pidgey", "Slowpoke", "Kadabra", "Graveler", "Chansey", "Machoke", "Mr. Mime",
        "Hitmonlee", "Hitmonchan", "Arbok", "Parasect", "Psyduck", "Drowzee", "Golem", "MissingNo.",
        "Magmar", "MissingNo.", "Electabuzz", "Magneton", "Koffing", "MissingNo.", "Mankey", "Seel",
        "Diglett", "Tauros", "MissingNo.", "MissingNo.", "MissingNo.", "Farfetch'd", "Venonat",
        "Dragonite", "MissingNo.", "MissingNo.", "MissingNo.", "Doduo", "Poliwag", "Jynx", "Moltres",
        "Articuno", "Zapdos", "Ditto", "Meowth", "Krabby", "MissingNo.", "MissingNo.", "MissingNo.",
        "Vulpix", "Ninetales", "Pikachu", "Raichu", "MissingNo.", "MissingNo.", "Dratini", "Dragonair",
        "Kabuto", "Kabutops", "Horsea", "Seadra", "MissingNo.", "MissingNo.", "Sandshrew", "Sandslash",
        "Omanyte", "Omastar", "Jigglypuff", "Wigglytuff", "Eevee", "Flareon", "Jolteon", "Vaporeon",
        "Machop", "Zubat", "Ekans", "Paras", "Poliwhirl", "Poliwrath", "Weedle", "Kakuna", "Beedrill",
        "MissingNo.", "Dodrio", "Primeape", "Dugtrio", "Venomoth", "Dewgong", "MissingNo.", "MissingNo.",
        "Caterpie", "Metapod", "Butterfree", "Machamp", "MissingNo.", "Golduck", "Hypno", "Golbat",
        "Mewtwo", "Snorlax", "Magikarp", "MissingNo.", "MissingNo.", "Muk", "MissingNo.", "Kingler",
        "Cloyster", "MissingNo.", "Electrode", "Clefable", "Weezing", "Persian", "Marowak", "MissingNo.",
        "Haunter", "Abra", "Alakazam", "Pidgeotto", "Pidgeot", "Starmie", "Bulbasaur", "Venusaur",
        "Tentacruel", "MissingNo.", "Goldeen", "Seaking", "MissingNo.", "MissingNo.", "MissingNo.",
        "MissingNo.", "Ponyta", "Rapidash", "Rattata", "Raticate", "Nidorino", "Nidorina", "Geodude",
        "Porygon", "Aerodactyl", "MissingNo.", "Magnemite", "MissingNo.", "MissingNo.", "Charmander",
        "Squirtle", "Charmeleon", "Wartortle", "Charizard", "MissingNo.", "MissingNo.", "MissingNo.",
        "MissingNo.", "Oddish", "Gloom", "Vileplume", "Bellsprout", "Weepinbell", "Victreebel"
    ]
    
    # Gen1 type IDs (different from later generations)
    TYPE_NAMES = {
        0x00: "Normal",
        0x01: "Fighting",
        0x02: "Flying",
        0x03: "Poison",
        0x04: "Ground",
        0x05: "Rock",
        0x07: "Bug",
        0x08: "Ghost",
        0x14: "Fire",
        0x15: "Water",
        0x16: "Grass",
        0x17: "Electric",
        0x18: "Psychic",
        0x19: "Ice",
        0x1A: "Dragon"
    }
    
    # Gen1 character map (simplified - you may need the full map)
    GB_CHARMAP = {
        0x00: " ",  # Space
        0x01: "A", 0x02: "B", 0x03: "C", 0x04: "D", 0x05: "E",
        0x06: "F", 0x07: "G", 0x08: "H", 0x09: "I", 0x0A: "J",
        0x0B: "K", 0x0C: "L", 0x0D: "M", 0x0E: "N", 0x0F: "O",
        0x10: "P", 0x11: "Q", 0x12: "R", 0x13: "S", 0x14: "T",
        0x15: "U", 0x16: "V", 0x17: "W", 0x18: "X", 0x19: "Y",
        0x1A: "Z", 0x1B: "(", 0x1C: ")", 0x1D: ":", 0x1E: ";",
        0x1F: "[", 0x20: "]", 0x21: "a", 0x22: "b", 0x23: "c",
        0x24: "d", 0x25: "e", 0x26: "f", 0x27: "g", 0x28: "h",
        0x29: "i", 0x2A: "j", 0x2B: "k", 0x2C: "l", 0x2D: "m",
        0x2E: "n", 0x2F: "o", 0x30: "p", 0x31: "q", 0x32: "r",
        0x33: "s", 0x34: "t", 0x35: "u", 0x36: "v", 0x37: "w",
        0x38: "x", 0x39: "y", 0x3A: "z", 0x50: "",  # 0x50 is terminator
    }
    
    def __init__(self, memory_reader):
        """
        Initialize the Gen1PartyReader
        
        Args:
            memory_reader: An object with methods to read memory (read_byte, read_u16_be, etc.)
        """
        self.memory = memory_reader
    
    def read_party(self, addresses: Dict[str, int]) -> List[Dict[str, Any]]:
        """
        Read the entire party from memory
        
        Args:
            addresses: Dictionary with 'partyAddr', 'partySlotsCounterAddr', 'partyNicknamesAddr'
            
        Returns:
            List of Pokémon data dictionaries
        """
        if not addresses.get('partyAddr') or not addresses.get('partySlotsCounterAddr'):
            return []
        
        party_addr = addresses['partyAddr']
        party_slots_counter_addr = addresses['partySlotsCounterAddr']
        party_nicknames_addr = addresses.get('partyNicknamesAddr')
        
        # Read party size (0-based count)
        party_slots_counter = self.memory.read_byte(party_slots_counter_addr) - 1
        
        party = []
        for i in range(min(party_slots_counter + 1, 6)):
            pokemon = self._read_pokemon(party_addr, i, party_nicknames_addr)
            party.append(pokemon)
        
        return party
    
    def _read_pokemon(self, party_addr: int, slot: int, party_nicknames_addr: Optional[int]) -> Dict[str, Any]:
        """
        Read a single Pokémon from memory
        
        Args:
            party_addr: Base party address
            slot: Party slot index (0-based)
            party_nicknames_addr: Base nickname address
            
        Returns:
            Pokémon data dictionary
        """
        # Gen1 party structure: each Pokemon is 0x2C (44) bytes
        pokemon_start = party_addr + (slot * 0x2C)
        
        # Read species ID
        species_id = self.memory.read_byte(pokemon_start)
        if species_id == 0:
            return {'speciesID': 0}
        
        # Read basic data
        cur_hp = self.memory.read_u16_be(pokemon_start + 0x1)
        level = self.memory.read_byte(pokemon_start + 0x21)  # Actual level
        status = self.memory.read_byte(pokemon_start + 0x4)
        type1 = self.memory.read_byte(pokemon_start + 0x5)
        type2 = self.memory.read_byte(pokemon_start + 0x6)
        catch_rate = self.memory.read_byte(pokemon_start + 0x7)
        move1 = self.memory.read_byte(pokemon_start + 0x8)
        move2 = self.memory.read_byte(pokemon_start + 0x9)
        move3 = self.memory.read_byte(pokemon_start + 0xA)
        move4 = self.memory.read_byte(pokemon_start + 0xB)
        otid = self.memory.read_u16_be(pokemon_start + 0xC)
        
        # Experience (3 bytes, big endian)
        exp_addr = pokemon_start + 0xE
        experience = (0x10000 * self.memory.read_byte(exp_addr) +
                      0x100 * self.memory.read_byte(exp_addr + 0x1) +
                      self.memory.read_byte(exp_addr + 0x2))
        
        # HP EVs and stats (2 bytes each)
        hp_ev = self.memory.read_u16_be(pokemon_start + 0x11)
        attack_ev = self.memory.read_u16_be(pokemon_start + 0x13)
        defense_ev = self.memory.read_u16_be(pokemon_start + 0x15)
        speed_ev = self.memory.read_u16_be(pokemon_start + 0x17)
        special_ev = self.memory.read_u16_be(pokemon_start + 0x19)
        
        # DVs (Determinant Values) - 2 bytes
        dvs_addr = pokemon_start + 0x1B
        atk_dv, def_dv, spe_dv, spc_dv = self._get_dvs(dvs_addr)
        hp_dv = self._calculate_hp_dv(atk_dv, def_dv, spe_dv, spc_dv)
        
        # PP (4 bytes)
        pp1 = self.memory.read_byte(pokemon_start + 0x1D)
        pp2 = self.memory.read_byte(pokemon_start + 0x1E)
        pp3 = self.memory.read_byte(pokemon_start + 0x1F)
        pp4 = self.memory.read_byte(pokemon_start + 0x20)
        
        # Stats
        max_hp = self.memory.read_u16_be(pokemon_start + 0x22)
        attack = self.memory.read_u16_be(pokemon_start + 0x24)
        defense = self.memory.read_u16_be(pokemon_start + 0x26)
        speed = self.memory.read_u16_be(pokemon_start + 0x28)
        special = self.memory.read_u16_be(pokemon_start + 0x2A)
        
        # Get species name
        species_name = self.SPECIES_NAMES[species_id - 1] if 1 <= species_id <= len(self.SPECIES_NAMES) else "Unknown"
        
        # Read nickname from separate nickname area
        nickname = self._read_nickname(party_nicknames_addr, slot)
        if not nickname:
            nickname = species_name
        
        # Check if shiny (Gen1 shiny determination)
        is_shiny = self._is_shiny_gen1(atk_dv, def_dv, spe_dv, spc_dv)
        
        return {
            'speciesID': species_id,
            'speciesName': species_name,
            'nickname': nickname,
            'level': level,
            'curHP': cur_hp,
            'maxHP': max_hp,
            'attack': attack,
            'defense': defense,
            'speed': speed,
            'spAttack': special,
            'spDefense': special,  # Gen1 uses same stat for SpAtk and SpDef
            'type1': type1,
            'type2': type2,
            'type1Name': self._get_type_name(type1),
            'type2Name': self._get_type_name(type2),
            'status': status,
            'experience': experience,
            'nature': 0,           # Gen1 doesn't have natures
            'natureName': "None",
            'move1': move1,
            'move2': move2,
            'move3': move3,
            'move4': move4,
            'pp1': pp1,
            'pp2': pp2,
            'pp3': pp3,
            'pp4': pp4,
            'evHP': hp_ev,
            'evAttack': attack_ev,
            'evDefense': defense_ev,
            'evSpeed': speed_ev,
            'evSpAttack': special_ev,
            'evSpDefense': special_ev,
            'ivHP': hp_dv,
            'ivAttack': atk_dv,
            'ivDefense': def_dv,
            'ivSpeed': spe_dv,
            'ivSpAttack': spc_dv,
            'ivSpDefense': spc_dv,
            'tid': otid,
            'sid': 0,              # Gen1 doesn't have SID
            'isShiny': is_shiny,
            'heldItem': "None",    # Gen1 doesn't have held items
            'friendship': 0,       # Gen1 doesn't have friendship
            'ability': 0,          # Gen1 doesn't have abilities
            'abilityName': "None",
            'abilityID': 0,
            'hiddenPower': 0,      # Gen1 doesn't have hidden power
            'hiddenPowerName': "None",
            'catchRate': catch_rate,
        }
    
    def _get_dvs(self, dvs_addr: int) -> Tuple[int, int, int, int]:
        """Extract DVs from the 2-byte DV value"""
        atk_def_dvs = self.memory.read_byte(dvs_addr)
        spe_spc_dvs = self.memory.read_byte(dvs_addr + 0x1)
        
        atk_dv = atk_def_dvs >> 4
        def_dv = atk_def_dvs & 0xF
        spe_dv = spe_spc_dvs >> 4
        spc_dv = spe_spc_dvs & 0xF
        
        return atk_dv, def_dv, spe_dv, spc_dv
    
    def _calculate_hp_dv(self, atk_dv: int, def_dv: int, spe_dv: int, spc_dv: int) -> int:
        """Calculate HP DV from other DVs"""
        return ((atk_dv % 2) * 8) + ((def_dv % 2) * 4) + ((spe_dv % 2) * 2) + (spc_dv % 2)
    
    def _is_shiny_gen1(self, atk_dv: int, def_dv: int, spe_dv: int, spc_dv: int) -> bool:
        """
        Determine if a Gen1 Pokémon is shiny (retroactive Gen2 shiny determination)
        """
        return (def_dv == 0xA and spe_dv == 0xA and spc_dv == 0xA and
                atk_dv in (0x2, 0x3, 0x6, 0x7, 0xA, 0xB, 0xE, 0xF))
    
    def _get_type_name(self, type_id: int) -> str:
        """Get the name of a Gen1 type"""
        return self.TYPE_NAMES.get(type_id, f"Unknown({type_id})")
    
    def _read_nickname(self, party_nicknames_addr: Optional[int], slot: int) -> str:
        """
        Read a Pokémon's nickname from the nickname area
        Each nickname is 11 bytes, terminated by 0x50
        """
        if not party_nicknames_addr:
            return ""
        
        nickname_addr = party_nicknames_addr + (slot * 11)  # Each nickname is 11 bytes
        nickname_chars = []
        
        for i in range(11):
            byte = self.memory.read_byte(nickname_addr + i)
            if byte == 0x50:  # Gen1 string terminator
                break
            elif byte != 0:
                char = self.GB_CHARMAP.get(byte, "")
                nickname_chars.append(char)
        
        return ''.join(nickname_chars)


# # Example memory reader implementation (for testing)
# class SimpleMemoryReader:
#     """Simple memory reader for testing - replace with actual implementation"""
    
#     def __init__(self, memory_data):
#         self.memory = memory_data
    
#     def read_byte(self, address):
#         return self.memory.get(address, 0)
    
#     def read_u16_be(self, address):
#         """Read a 16-bit big-endian value"""
#         high = self.read_byte(address)
#         low = self.read_byte(address + 1)
#         return (high << 8) | low


# # Usage example
# if __name__ == "__main__":
#     # This is just an example - you'll need actual memory data from a Gen1 game
#     memory_data = {}  # Fill with actual memory data
#     memory_reader = SimpleMemoryReader(memory_data)
    
#     addresses = {
#         'partyAddr': 0x0000,           # Example address
#         'partySlotsCounterAddr': 0x0001,
#         'partyNicknamesAddr': 0x0010,
#     }
    
#     reader = Gen1PartyReader(memory_reader)
#     party = reader.read_party(addresses)
    
#     for i, pokemon in enumerate(party):
#         print(f"Slot {i + 1}: {pokemon.get('nickname', 'Unknown')} (Level {pokemon.get('level', 0)})")