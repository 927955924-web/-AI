"""
Utility functions for knowledge base shop matching.
"""
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def infer_shop_id(owner_id, shop_id=None, shop_name=None, account=None):
    """
    Infer the correct shop_id for a knowledge base entry.
    
    Matching priority:
    1. If shop_id is already provided and valid, return it directly
    2. If owner has only one shop, return that shop's id
    3. Match by shop_name (exact then fuzzy)
    4. Match by account
    5. Return None if no match found
    
    Args:
        owner_id: The owner user id
        shop_id: Existing shop_id (may be None)
        shop_name: Shop name to match against
        account: Account to match against
    
    Returns:
        shop_id string or None
    """
    if not owner_id:
        return shop_id

    # If shop_id already exists, validate and return
    if shop_id:
        from apps.shops.models import Shop
        if Shop.objects.filter(shop_id=shop_id).exists():
            return shop_id
        logger.warning(f"[ShopMatch] Invalid shop_id '{shop_id}' for owner {owner_id}")

    # Get all shops for this owner
    from apps.shops.models import Shop
    owner_shops = list(
        Shop.objects.filter(owner_id=owner_id, is_active=True)
        .values_list('shop_id', 'shop_name', 'account')
    )

    if not owner_shops:
        logger.debug(f"[ShopMatch] Owner {owner_id} has no shops")
        return None

    # Single shop - direct match
    if len(owner_shops) == 1:
        matched_id = owner_shops[0][0]
        logger.info(f"[ShopMatch] Owner {owner_id} has single shop, auto-matched to {matched_id}")
        return matched_id

    # Multiple shops - try matching by name
    if shop_name:
        # Exact match first
        for sid, sname, saccount in owner_shops:
            if sname and sname == shop_name:
                logger.info(f"[ShopMatch] Exact name match: '{shop_name}' -> {sid}")
                return sid

        # Fuzzy match (threshold 0.8)
        best_ratio = 0
        best_sid = None
        for sid, sname, saccount in owner_shops:
            if sname:
                ratio = SequenceMatcher(None, shop_name.lower(), sname.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_sid = sid

        if best_ratio >= 0.8 and best_sid:
            logger.info(
                f"[ShopMatch] Fuzzy name match: '{shop_name}' -> {best_sid} "
                f"(similarity: {best_ratio:.2f})"
            )
            return best_sid

    # Try matching by account
    if account:
        for sid, sname, saccount in owner_shops:
            if saccount and saccount == account:
                logger.info(f"[ShopMatch] Account match: '{account}' -> {sid}")
                return sid

        # Fuzzy account match
        best_ratio = 0
        best_sid = None
        for sid, sname, saccount in owner_shops:
            if saccount:
                ratio = SequenceMatcher(None, account.lower(), saccount.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_sid = sid

        if best_ratio >= 0.8 and best_sid:
            logger.info(
                f"[ShopMatch] Fuzzy account match: '{account}' -> {best_sid} "
                f"(similarity: {best_ratio:.2f})"
            )
            return best_sid

    logger.warning(
        f"[ShopMatch] Cannot infer shop for owner {owner_id} "
        f"(name='{shop_name}', account='{account}', shops={len(owner_shops)})"
    )
    return None
