// Shapes for the /json/gameinfo/ response and game data round-trip.

export interface AuthorTypes {
  roles: {id: number; title: string}[];
  authors: {id: number; name: string}[];
  value: {role: number; author: number}[];
}

export interface TagTypes {
  categories: {
    id: number;
    name: string;
    allow_new_tags: boolean;
    tags: {id: number; name: string}[];
  }[];
}

export interface LinkCategory {
  id: number;
  title: string;
  uploadable: boolean;
}

export interface LinkTypes {
  categories: LinkCategory[];
}

// Pairs are [catId, valId] for authors/tags; links are [catId, desc, url].
export type Pair = [number | string, number | string];
export type Link = [number | string, string, string];

export interface GameData {
  title?: string;
  desc?: string;
  description_attributions?: string[];
  release_date?: string;
  authors?: Pair[];
  tags?: Pair[];
  links?: Link[];
}

export interface GameInfo {
  authortypes: AuthorTypes;
  tagtypes: TagTypes;
  linktypes: LinkTypes;
  gamedata?: GameData;
}

// /json/import/ returns either GameData fields or an error.
export type ImportResult = GameData & {error?: string};
