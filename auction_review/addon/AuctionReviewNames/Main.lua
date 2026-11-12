-- Auction Review Names
-- Records the name, quality and icon of every item in Auctionator's price
-- database so the Auction Review dashboard can show names instead of IDs.
-- Data is only written to disk when you log out or type /reload.

local GetItemInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
local RequestLoad = C_Item and C_Item.RequestLoadItemDataByID

local BATCH_SIZE = 40      -- items checked per tick
local TICK_SECONDS = 0.1
local MAX_ATTEMPTS = 3

local queue, queued, attempts = {}, {}, {}
local ticker

local function Record(itemID)
  local name, _, quality, _, _, _, _, _, _, icon = GetItemInfo(itemID)
  if name then
    AUCTION_REVIEW_ITEM_NAMES[itemID] = { name = name, quality = quality, icon = icon }
    return true
  end
  return false
end

local function RecordPet(speciesID)
  if not (C_PetJournal and C_PetJournal.GetPetInfoBySpeciesID) then return end
  local name, icon = C_PetJournal.GetPetInfoBySpeciesID(speciesID)
  if name then
    AUCTION_REVIEW_PET_NAMES[speciesID] = { name = name, icon = icon }
  end
end

local Tick

local function Enqueue(itemID)
  if not queued[itemID] and not AUCTION_REVIEW_ITEM_NAMES[itemID] then
    queued[itemID] = true
    queue[#queue + 1] = itemID
    if not ticker then
      ticker = C_Timer.NewTicker(TICK_SECONDS, Tick)
    end
  end
end

function Tick()
  local done = 0
  while done < BATCH_SIZE and #queue > 0 do
    local itemID = table.remove(queue)
    queued[itemID] = nil
    if not Record(itemID) then
      attempts[itemID] = (attempts[itemID] or 0) + 1
      if RequestLoad then RequestLoad(itemID) end
      if attempts[itemID] < MAX_ATTEMPTS then
        -- retry later; GET_ITEM_INFO_RECEIVED usually records it first
        C_Timer.After(2, function() Enqueue(itemID) end)
      end
    end
    done = done + 1
  end
  if #queue == 0 and ticker then
    ticker:Cancel()
    ticker = nil
  end
end

local function Scan()
  local db = Auctionator and Auctionator.Database and Auctionator.Database.db
  if type(db) ~= "table" then return end
  for key in pairs(db) do
    local k = tostring(key)
    local petID = k:match("^p:(%d+)")
    if petID then
      petID = tonumber(petID)
      if not AUCTION_REVIEW_PET_NAMES[petID] then RecordPet(petID) end
    else
      local itemID = tonumber(k:match("^g:(%d+)") or k:match("^(%d+)$"))
      if itemID then Enqueue(itemID) end
    end
  end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("GET_ITEM_INFO_RECEIVED")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:SetScript("OnEvent", function(_, event, itemID, success)
  if event == "PLAYER_LOGIN" then
    AUCTION_REVIEW_ITEM_NAMES = AUCTION_REVIEW_ITEM_NAMES or {}
    AUCTION_REVIEW_PET_NAMES = AUCTION_REVIEW_PET_NAMES or {}
    C_Timer.After(10, Scan)
  elseif event == "GET_ITEM_INFO_RECEIVED" then
    if AUCTION_REVIEW_ITEM_NAMES and itemID and success and not AUCTION_REVIEW_ITEM_NAMES[itemID] then
      Record(itemID)
    end
  elseif event == "AUCTION_HOUSE_CLOSED" then
    -- pick up items added by scans this session
    C_Timer.After(2, Scan)
  end
end)

SLASH_AUCTIONREVIEWNAMES1 = "/arnames"
SlashCmdList.AUCTIONREVIEWNAMES = function()
  local items, pets = 0, 0
  for _ in pairs(AUCTION_REVIEW_ITEM_NAMES or {}) do items = items + 1 end
  for _ in pairs(AUCTION_REVIEW_PET_NAMES or {}) do pets = pets + 1 end
  print(("|cff66ccffAuction Review Names|r: %d items, %d pets saved, %d still queued. /reload to write them to disk.")
    :format(items, pets, #queue))
  Scan()
end
