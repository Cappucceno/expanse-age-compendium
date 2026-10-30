# The Expanse RPG Compendium for AGE System

A Foundry VTT v14 **module** for the [AGE System (unofficial)](https://github.com/vkdolea/age-system) (`age-system` 5.0.0+).
It carries the compendium content of **The Expanse RPG: Transport Union Edition** (Green Ronin, 2025), converted to AGE System
item and actor types, to be used with the **The Expanse** preset (Fortune, Income, Churn, profession/origin).
Version 2.0.0 replaces the content of 1.0.0, which came from the earlier edition of the book.

| Compendium | Content (AGE type) |
|---|---|
| Talents and Specializations | 55 `talent` items: 40 talents and 15 specializations, Novice/Expert/Master in `degree0..2` |
| Ability Focuses | 64 `focus` items (ability set, +2) |
| Stunts | 147 `stunts` items: general, chase, gun, grappling, melee, vehicle, exploration, investigation, social, attitude, membership and spaceship crew stunts |
| Weapons | 28 `weapon` items: close weapons, pistols, rifles, grenades and the generic weapons of the Attack Damage table |
| Armor / Shields | 7 + 2 `equipment` items (armor bonus, armor penalty and Defense as modifiers) |
| Equipment | 34 `equipment` items: electronics, survival gear, drones, mechs and tools |
| Enhancement Implants | 26 `equipment` items from the implant catalog, with their slots |
| Sample Spaceships | 15 `spaceship` actors (size, hull dice, crew, sensors, weapons as ship features) |
| Adversaries and Named Characters | 48 `char` actors with focuses and weapons as embedded items: 37 adversaries, supporting characters and Zeroes, and the 11 named characters of the setting chapters |
| Character Creation Guide / Tables | Chapter 2 text, origins, 12 backgrounds, 24 professions and 12 drives as journals; 27 roll tables (social class, backgrounds, professions, benefits, drives, abilities) |
| Setting Guide | Chapters 7 to 11 and 15 as journals |
| Rules Reference / Tables | Chapters 1, 3 to 6 and 12 to 14 as journals; Churn Over and NPC Attitude roll tables |

Documents are grouped into folders inside each compendium. Texts are in English; with the **Babele** module active and the
language set to Português (Brasil), names follow the terminology of the Jambô Editora edition (names only; entries of the new edition that
have no Brazilian name yet stay in English).

## Install
Manifest URL (once a release `v2.0.0` with `module.zip` exists):
`https://raw.githubusercontent.com/Cappucceno/expanse-age-compendium/main/module.json`

Manual install: put this folder in `Data/modules/` **named `expanse-age-compendium`**, restart Foundry, and enable it in a world that uses the AGE System.

## Building
Requires `poppler-utils`, Python 3 and Node.
```bash
npm install
python3 scripts/convert.py "/path/to/The_Expanse_-_Transport_Union_Edition.pdf"   # PDF -> packs/_source/*.json
npm run build                                                                      # packs/_source -> packs/<pack> (LevelDB)
```
`--only talents,stunts,...` converts a subset. The converter reads the PDF pages directly, so it is tied to this edition of the book.

## Notes
- Not tested inside Foundry yet. Document ids are generated from the pack and the name, so they differ from those of version 1.0.0.
- Journal text is rebuilt from the PDF by position and font: headings, bold/italic, bullets are recognised, but tables and sidebars can come out imperfect
  (the important tables are rolled tables or items). Text that the book wraps around artwork can be incomplete in a few equipment entries.
- Weapons of this edition only list a cost; their damage and range come from the Attack Damage and Weapon Range tables of Chapter 5 (and are noted in the item).
  The Sword and the Stun Baton have no printed category: the sword is treated as a heavy and the stun baton as a light close weapon.
- Corrections of printing errors: the Brawler profession has its focus and talent swapped in the book, the Networker drive lists "Contract" for the Contacts talent,
  and the talent printed as "Protect" is named Protector, as in the table of contents and the drives.
- See [NOTICE.md](NOTICE.md) for copyright and credits (Green Ronin Publishing, Daniel Abraham and Ty Franck, Jambô Editora).
