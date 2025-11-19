#!/usr/bin/env python3
"""
Patch rcsbapi to use HTTPS instead of HTTP for schema URLs.

This fixes the "Connection refused" error when the HTTP schema URL is blocked
by firewalls or cloud providers that only allow HTTPS.
"""
import sys
import os

def patch_rcsbapi():
    """Patch the rcsbapi const.py file to use HTTPS for all URLs."""
    try:
        import rcsbapi.const as const

        # Get the file path
        const_file = const.__file__

        print(f"🔧 Patching rcsbapi at: {const_file}")

        # Read the file
        with open(const_file, 'r') as f:
            content = f.read()

        # Check if already patched
        if 'http://search.rcsb.org' not in content:
            print("✅ rcsbapi already patched or using HTTPS")
            return True

        # Replace HTTP with HTTPS for the schema URL
        original = 'SEARCH_API_STRUCTURE_ATTRIBUTE_SCHEMA_URL: str = "http://search.rcsb.org/rcsbsearch/v2/metadata/schema"'
        patched = 'SEARCH_API_STRUCTURE_ATTRIBUTE_SCHEMA_URL: str = "https://search.rcsb.org/rcsbsearch/v2/metadata/schema"'

        if original in content:
            content = content.replace(original, patched)

            # Write back
            with open(const_file, 'w') as f:
                f.write(content)

            print("✅ Successfully patched rcsbapi to use HTTPS")
            print(f"   Changed: http://search.rcsb.org → https://search.rcsb.org")
            return True
        else:
            print("⚠️  Could not find exact string to patch")
            print("   Attempting broader replacement...")

            # Broader replacement as fallback
            content = content.replace(
                '"http://search.rcsb.org',
                '"https://search.rcsb.org'
            )

            with open(const_file, 'w') as f:
                f.write(content)

            print("✅ Applied broader HTTPS patch")
            return True

    except Exception as e:
        print(f"❌ Error patching rcsbapi: {e}")
        return False

if __name__ == "__main__":
    success = patch_rcsbapi()
    sys.exit(0 if success else 1)
