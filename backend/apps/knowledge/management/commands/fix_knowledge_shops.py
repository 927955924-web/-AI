"""
Management command to fix knowledge base entries with missing shop associations.
Scans entries where shop is NULL but owner exists, and infers the correct shop.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.knowledge.models import KnowledgeBase
from apps.knowledge.utils import infer_shop_id
from apps.shops.models import Shop


class Command(BaseCommand):
    help = 'Fix knowledge base entries with missing shop associations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them',
        )
        parser.add_argument(
            '--owner-id',
            type=int,
            help='Only fix entries for a specific owner',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        owner_id = options.get('owner_id')

        # Find entries with missing shop
        qs = KnowledgeBase.objects.filter(shop__isnull=True, owner__isnull=False)
        if owner_id:
            qs = qs.filter(owner_id=owner_id)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No entries with missing shop found.'))
            return

        self.stdout.write(f'Found {total} knowledge entries with missing shop.')

        # Group by owner
        owner_entries = defaultdict(list)
        for entry in qs.select_related('owner').iterator():
            owner_entries[entry.owner_id].append(entry)

        fixed = 0
        skipped = 0

        for oid, entries in owner_entries.items():
            # Get owner's shops for display
            shops = list(
                Shop.objects.filter(owner_id=oid, is_active=True)
                .values_list('shop_id', 'shop_name', 'account')
            )
            shop_count = len(shops)

            if shop_count == 0:
                self.stdout.write(
                    self.style.WARNING(f'  Owner {oid}: no active shops, skipping {len(entries)} entries')
                )
                skipped += len(entries)
                continue

            shop_info = ', '.join(f'{s[1]}({s[0]})' for s in shops)
            self.stdout.write(f'  Owner {oid}: {len(entries)} entries, {shop_count} shops [{shop_info}]')

            to_update = []
            for entry in entries:
                resolved = infer_shop_id(owner_id=oid)
                if resolved:
                    entry.shop_id = resolved
                    to_update.append(entry)
                else:
                    skipped += 1

            if to_update:
                if dry_run:
                    self.stdout.write(
                        self.style.NOTICE(f'    [DRY-RUN] Would fix {len(to_update)} entries')
                    )
                else:
                    KnowledgeBase.objects.bulk_update(to_update, ['shop_id'], batch_size=500)
                    self.stdout.write(
                        self.style.SUCCESS(f'    Fixed {len(to_update)} entries')
                    )
                fixed += len(to_update)

        self.stdout.write('')
        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Summary: {fixed} fixed, {skipped} skipped, {total} total'
        ))
