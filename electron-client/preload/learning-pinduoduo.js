/**
 * Pinduoduo Learning Preload Script
 * Extracts product information from mms.pinduoduo.com for knowledge base learning
 * 
 * Flow:
 * 1. On list page: identify checked products, click title to open detail page
 * 2. On detail page: scroll page, extract content, notify main process
 * 3. Main process: navigate back, continue to next product
 */
const { ipcRenderer } = require('electron');

const PLATFORM_ID = 'pinduoduo';

// Local state (synced with main process)
let state = {
  isExtracting: false,
  extractedProducts: [],
  pendingProducts: [],
  currentProductIndex: 0,
  totalProducts: 0,
  listPageUrl: '',
  isOnDetailPage: false,
  detailUrlTemplate: '',  // Captured from first successful detail page navigation
  currentPageNumber: 1,   // Current pagination page number
  pageSize: 10            // Items per page (user may set to 200)
};

// Guard against double-processing (multiple triggers for processNextProduct)
let _processingScheduled = false;
let _detailHandled = false;

/**
 * Sync state with main process
 */
async function syncStateToMain() {
  await ipcRenderer.invoke('learning:set-state', PLATFORM_ID, {
    isExtracting: state.isExtracting,
    pendingProducts: state.pendingProducts,
    currentProductIndex: state.currentProductIndex,
    totalProducts: state.totalProducts,
    listPageUrl: state.listPageUrl,
    extractedProducts: state.extractedProducts,
    detailUrlTemplate: state.detailUrlTemplate,
    currentPageNumber: state.currentPageNumber,
    pageSize: state.pageSize
  });
}

/**
 * Load state from main process
 */
async function loadStateFromMain() {
  const mainState = await ipcRenderer.invoke('learning:get-state', PLATFORM_ID);
  if (mainState && mainState.isExtracting) {
    state.isExtracting = mainState.isExtracting;
    state.pendingProducts = mainState.pendingProducts || [];
    state.currentProductIndex = mainState.currentProductIndex || 0;
    state.totalProducts = mainState.totalProducts || 0;
    state.listPageUrl = mainState.listPageUrl || '';
    state.extractedProducts = mainState.extractedProducts || [];
    state.detailUrlTemplate = mainState.detailUrlTemplate || '';
    state.currentPageNumber = mainState.currentPageNumber || 1;
    state.pageSize = mainState.pageSize || 10;
    log(`State restored from main: extracting=${state.isExtracting}, index=${state.currentProductIndex}/${state.totalProducts}, page=${state.currentPageNumber}, pageSize=${state.pageSize}`);
    return true;
  }
  return false;
}

/**
 * Log message to main process
 */
function log(message, level = 'info') {
  console.log(`[Learning-PDD][${level}] ${message}`);
  ipcRenderer.send('learning:log', { platform: PLATFORM_ID, message, level });
}

/**
 * Sleep helper
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Get current page number from pagination UI
 */
function getCurrentPageNumber() {
  // Strategy 1: Beast-core pagination data-status
  // Format: "beast-core-pagination-{pageSize}-{currentPage}"
  const pagination = document.querySelector('[data-testid="beast-core-pagination"]');
  if (pagination) {
    const status = pagination.getAttribute('data-status') || '';
    const match = status.match(/beast-core-pagination-(\d+)-(\d+)/);
    if (match) {
      return parseInt(match[2]);
    }
    // Try active page item
    const activePage = pagination.querySelector('[class*="PGT_active"], [class*="active"]');
    if (activePage) {
      const num = parseInt(activePage.textContent.trim());
      if (!isNaN(num) && num > 0) return num;
    }
  }
  
  // Strategy 2: Ant Design pagination (fallback)
  const activePageSelectors = [
    '.ant-pagination-item-active',
    '.ant-pagination-item-active a',
    '[class*="pagination"] [class*="active"]',
    'li.active a'
  ];
  for (const selector of activePageSelectors) {
    try {
      const activeEl = document.querySelector(selector);
      if (activeEl) {
        const pageNum = parseInt(activeEl.textContent.trim());
        if (!isNaN(pageNum) && pageNum > 0) return pageNum;
      }
    } catch (e) {}
  }
  
  return 1;
}

/**
 * Get current page size (items per page) from pagination UI
 * PDD uses beast-core components, not Ant Design
 */
function getCurrentPageSize() {
  // Strategy 1: Read from beast-core pagination data-status attribute
  // Format: "beast-core-pagination-{pageSize}-{currentPage}"
  const pagination = document.querySelector('[data-testid="beast-core-pagination"]');
  if (pagination) {
    const status = pagination.getAttribute('data-status') || '';
    const match = status.match(/beast-core-pagination-(\d+)-(\d+)/);
    if (match) {
      const size = parseInt(match[1]);
      if (size > 0) {
        log(`Page size from beast-core data-status: ${size}`);
        return size;
      }
    }
    
    // Strategy 2: Read from beast-core select value inside size changer
    const sizeChanger = pagination.querySelector('[class*="PGT_sizeChanger"], [class*="sizeChanger"]');
    if (sizeChanger) {
      const selectInput = sizeChanger.querySelector('input, [class*="headInput"] input, [class*="selectValue"]');
      if (selectInput) {
        const val = selectInput.value || selectInput.textContent || '';
        const numMatch = val.match(/(\d+)/);
        if (numMatch) {
          const size = parseInt(numMatch[1]);
          if (size > 0) return size;
        }
      }
      // Try reading text content of the select header
      const selectHeader = sizeChanger.querySelector('[data-testid="beast-core-select-header"]');
      if (selectHeader) {
        const text = selectHeader.textContent || '';
        const numMatch = text.match(/(\d+)/);
        if (numMatch) {
          const size = parseInt(numMatch[1]);
          if (size > 0) return size;
        }
      }
    }
  }
  
  // Strategy 3: Search entire page for "每页 XX 条" pattern
  const pageText = document.body.innerText || document.body.textContent || '';
  const match1 = pageText.match(/每页\s*(\d+)\s*条/);
  if (match1) {
    const size = parseInt(match1[1]);
    if (size > 0) return size;
  }
  
  // Strategy 4: Look for Ant Design pagination (fallback for other platforms)
  const sizeSelectors = [
    '.ant-pagination-options-size-changer .ant-select-selection-item',
    '.ant-select-selection-selected-value',
    '.ant-pagination-options .ant-select-selector'
  ];
  for (const selector of sizeSelectors) {
    try {
      const el = document.querySelector(selector);
      if (el) {
        const text = (el.textContent || el.innerText || '').trim();
        const match = text.match(/(\d+)/);
        if (match) {
          const size = parseInt(match[1]);
          if (size > 0) return size;
        }
      }
    } catch (e) {}
  }
  
  return 10; // Default page size
}

/**
 * Set page size by interacting with beast-core pagination select component
 * Returns true if successfully changed
 */
async function setPageSize(targetSize) {
  const currentSize = getCurrentPageSize();
  if (currentSize === targetSize) {
    log(`Page size already set to ${targetSize}, no change needed`);
    return true;
  }
  
  log(`Changing page size from ${currentSize} to ${targetSize}...`);
  
  // Step 1: Find the beast-core select inside the pagination size changer
  let selectWrapper = null;
  
  // Try beast-core pagination first
  const pagination = document.querySelector('[data-testid="beast-core-pagination"]');
  if (pagination) {
    // Find the size changer <li> that contains "每页"
    const sizeChanger = pagination.querySelector('[class*="PGT_sizeChanger"], [class*="sizeChanger"]');
    if (sizeChanger) {
      selectWrapper = sizeChanger.querySelector('[data-testid="beast-core-select"]');
      log(`Found beast-core select in sizeChanger`);
    }
  }
  
  // Fallback: search by data-testid anywhere in pagination context
  if (!selectWrapper) {
    const allSelects = document.querySelectorAll('[data-testid="beast-core-select"]');
    for (const sel of allSelects) {
      const parent = sel.closest('[class*="PGT_"], [class*="paginat"], [data-testid="beast-core-pagination"]');
      if (parent) {
        selectWrapper = sel;
        log(`Found beast-core select via parent context`);
        break;
      }
    }
  }
  
  if (!selectWrapper) {
    log('Could not find beast-core pagination select, trying Ant Design fallback...', 'warn');
    return await setPageSizeAntDesign(targetSize);
  }
  
  // Step 2: Click the select header to open dropdown
  const selectHeader = selectWrapper.querySelector('[data-testid="beast-core-select-header"]') || selectWrapper;
  log(`Clicking beast-core select header...`);
  selectHeader.click();
  await sleep(500);
  
  // Step 3: Find the dropdown options
  // Beast-core select dropdown is usually appended to document.body as a portal
  const dropdownSelectors = [
    '[data-testid="beast-core-select-dropdown"]',
    '[class*="ST_dropdown"]',
    '[class*="ST_listWrapper"]',
    '[class*="select-dropdown"]'
  ];
  
  let dropdown = null;
  for (const selector of dropdownSelectors) {
    dropdown = document.querySelector(selector);
    if (dropdown && dropdown.offsetParent !== null) {
      log(`Found dropdown with selector: ${selector}`);
      break;
    }
    dropdown = null;
  }
  
  // Also try: the dropdown may be a sibling/child of the wrapper
  if (!dropdown) {
    dropdown = selectWrapper.querySelector('[class*="dropdown"], [class*="listWrapper"], ul, [role="listbox"]');
    if (dropdown) {
      log(`Found dropdown inside select wrapper`);
    }
  }
  
  if (!dropdown) {
    // Try finding any newly-visible dropdown on the page
    const allDropdowns = document.querySelectorAll('[class*="dropdown"], [role="listbox"]');
    for (const dd of allDropdowns) {
      if (dd.offsetParent !== null && dd.querySelectorAll('li, [class*="option"]').length > 0) {
        dropdown = dd;
        log(`Found visible dropdown by scanning page`);
        break;
      }
    }
  }
  
  if (!dropdown) {
    log('Could not find dropdown after clicking select header', 'warn');
    // Try pressing Escape to close any partial state
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
    return false;
  }
  
  // Step 4: Find and click the target option
  const options = dropdown.querySelectorAll('li, [class*="option"], [role="option"]');
  log(`Found ${options.length} options in dropdown`);
  
  for (const option of options) {
    const text = (option.textContent || '').trim();
    const match = text.match(/^(\d+)/);
    if (match && parseInt(match[1]) === targetSize) {
      log(`Clicking option: "${text}"`);
      option.click();
      await sleep(1500); // Wait for page to reload with new size
      
      // Verify the change
      const newSize = getCurrentPageSize();
      log(`Page size after change: ${newSize}`);
      return true;
    }
  }
  
  // Log all available options for debugging
  const optionTexts = Array.from(options).map(o => (o.textContent || '').trim()).join(', ');
  log(`Available options: [${optionTexts}], target ${targetSize} not found`, 'warn');
  
  // Close dropdown
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
  await sleep(200);
  
  return false;
}

/**
 * Fallback: Set page size using Ant Design selectors
 */
async function setPageSizeAntDesign(targetSize) {
  const sizeChangerSelectors = [
    '.ant-pagination-options-size-changer',
    '.ant-pagination-options .ant-select',
    '.ant-pagination .ant-select'
  ];
  
  let dropdown = null;
  for (const selector of sizeChangerSelectors) {
    dropdown = document.querySelector(selector);
    if (dropdown) break;
  }
  
  if (!dropdown) {
    log('Ant Design pagination dropdown also not found', 'warn');
    return false;
  }
  
  dropdown.click();
  await sleep(500);
  
  const options = document.querySelectorAll('.ant-select-dropdown .ant-select-item, .ant-select-item-option');
  for (const option of options) {
    const text = (option.textContent || '').trim();
    const match = text.match(/^(\d+)/);
    if (match && parseInt(match[1]) === targetSize) {
      option.click();
      await sleep(1500);
      return true;
    }
  }
  
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
  return false;
}

/**
 * Get total product count from pagination info
 * PDD beast-core: <li class="PGT_totalText">共有 36 条</li>
 */
function getTotalProductCount() {
  // Strategy 1: Beast-core pagination total text
  const totalTextEl = document.querySelector('[class*="PGT_totalText"], [class*="totalText"]');
  if (totalTextEl) {
    const text = totalTextEl.textContent || '';
    const match = text.match(/(\d+)/);
    if (match) {
      const count = parseInt(match[1]);
      log(`Found total count via beast-core totalText: ${count}`);
      return count;
    }
  }
  
  // Strategy 2: Beast-core pagination data-status (format: "beast-core-pagination-50-1")
  // The total isn't in data-status, but we can use total text from the full pagination area
  const pagination = document.querySelector('[data-testid="beast-core-pagination"]');
  if (pagination) {
    const text = pagination.textContent || '';
    const match = text.match(/共[有]?\s*(\d+)\s*条/);
    if (match) {
      return parseInt(match[1]);
    }
  }
  
  // Strategy 3: Search entire page for "共 XX 条" or "共有 XX 条"
  const pageText = document.body.innerText || document.body.textContent || '';
  const match1 = pageText.match(/共[有]?\s*(\d+)\s*条/);
  if (match1) {
    const count = parseInt(match1[1]);
    if (count > 0) {
      log(`Found total count via page text search: ${count}`);
      return count;
    }
  }
  
  // Strategy 4: Ant Design pagination (fallback)
  const paginationArea = document.querySelector('.ant-pagination');
  if (paginationArea) {
    const text = paginationArea.textContent || '';
    const match = text.match(/共\s*(\d+)\s*条|总[计共]\s*(\d+)/);
    if (match) {
      return parseInt(match[1] || match[2]);
    }
  }
  
  return null;
}

/**
 * Get optimal page size to fit all products
 * Available options: 10, 20, 50, 100
 */
function getOptimalPageSize(totalCount) {
  const sizes = [10, 20, 50, 100];
  for (const size of sizes) {
    if (size >= totalCount) {
      return size;
    }
  }
  return 100; // Max available
}

/**
 * Force page size to match the saved state (主动校准)
 * Instead of detecting and restoring, always force set to saved value
 */
async function ensurePageSize() {
  if (!state.pageSize || state.pageSize <= 10) {
    log(`No page size to force (state.pageSize=${state.pageSize})`);
    return true; // Default size, no need to force
  }
  
  log(`Forcing page size to ${state.pageSize} (校准显示数量)...`);
  
  // Wait for pagination component to be rendered (beast-core or ant-design)
  // After navigating back from detail page, the page needs time to fully render
  let paginationFound = false;
  const maxWaitAttempts = 10;  // 10 attempts * 600ms = 6 seconds max
  for (let waitAttempt = 0; waitAttempt < maxWaitAttempts; waitAttempt++) {
    // Check for beast-core pagination first (PDD uses this)
    const beastPagination = document.querySelector('[data-testid="beast-core-pagination"], [class*="PGT_pagination"]');
    if (beastPagination) {
      paginationFound = true;
      log(`Found beast-core pagination component on attempt ${waitAttempt + 1}`);
      break;
    }
    // Fallback: check for ant-design or generic pagination
    const paginationArea = document.querySelector('.ant-pagination, [class*="pagination"], [class*="pager"]');
    if (paginationArea && paginationArea.textContent && paginationArea.textContent.length > 5) {
      paginationFound = true;
      log(`Found pagination component on attempt ${waitAttempt + 1}`);
      break;
    }
    log(`Waiting for pagination component to load (attempt ${waitAttempt + 1})...`);
    await sleep(600);
  }
  
  if (!paginationFound) {
    log('Pagination component not found after extended wait, cannot force page size', 'warn');
    return false;
  }
  
  // Check current page size first - if already correct, skip
  const currentSize = getCurrentPageSize();
  if (currentSize === state.pageSize) {
    log(`Page size already correct: ${currentSize}`);
    return true;
  }
  
  // Force set page size (核心校准步骤)
  log(`Current size ${currentSize} differs from target ${state.pageSize}, forcing change...`);
  ipcRenderer.send('learning:progress', {
    platform: PLATFORM_ID,
    phase: 'restoring',
    message: `正在校准分页设置为每页 ${state.pageSize} 条...`
  });
  
  const restored = await setPageSize(state.pageSize);
  if (restored) {
    // Wait for table to reload after page size change
    await sleep(1500);
    // Verify restoration
    const verifySize = getCurrentPageSize();
    log(`Page size after forcing: ${verifySize}`);
    return verifySize === state.pageSize;
  }
  
  log(`Could not force page size to ${state.pageSize}`, 'warn');
  return false;
}

/**
 * Navigate to a specific page number by clicking on it
 * Returns true if navigation was successful
 */
async function navigateToPage(pageNumber) {
  if (pageNumber <= 0) {
    log('Invalid page number, skipping navigation');
    return false;
  }
  
  const currentPage = getCurrentPageNumber();
  if (currentPage === pageNumber) {
    log(`Already on page ${pageNumber}, no navigation needed`);
    return true;
  }
  
  log(`Navigating from page ${currentPage} to page ${pageNumber}...`);
  
  // Try to find and click the page number
  const pageSelectors = [
    `.ant-pagination-item[title="${pageNumber}"]`,
    `.ant-pagination-item:has(a:contains("${pageNumber}"))`,
    `[class*="pagination"] li[title="${pageNumber}"]`,
    `[class*="pagination"] a[title="${pageNumber}"]`,
    `[class*="pager"] [title="${pageNumber}"]`
  ];
  
  for (const selector of pageSelectors) {
    try {
      const pageEl = document.querySelector(selector);
      if (pageEl) {
        pageEl.click();
        await sleep(1500); // Wait for page to load
        const newPage = getCurrentPageNumber();
        if (newPage === pageNumber) {
          log(`Successfully navigated to page ${pageNumber}`);
          return true;
        }
      }
    } catch (e) {}
  }
  
  // Fallback: find page number in pagination items by text content
  const paginationItems = document.querySelectorAll(
    '.ant-pagination-item, [class*="pagination"] li, [class*="pager"] li'
  );
  
  for (const item of paginationItems) {
    const text = item.textContent.trim();
    const itemPage = parseInt(text);
    if (itemPage === pageNumber) {
      item.click();
      await sleep(1500);
      const newPage = getCurrentPageNumber();
      if (newPage === pageNumber) {
        log(`Successfully navigated to page ${pageNumber} (via text match)`);
        return true;
      }
    }
  }
  
  // Another fallback: find <a> tags with page number
  const allLinks = document.querySelectorAll('[class*="pagination"] a, [class*="pager"] a');
  for (const link of allLinks) {
    const text = link.textContent.trim();
    if (text === String(pageNumber)) {
      link.click();
      await sleep(1500);
      log(`Clicked page link ${pageNumber}`);
      return true;
    }
  }
  
  log(`Could not find page ${pageNumber} in pagination`, 'warn');
  return false;
}

/**
 * Smooth scroll the page to trigger lazy loading
 */
async function scrollPage() {
  const scrollHeight = document.documentElement.scrollHeight;
  const viewportHeight = window.innerHeight;
  const scrollStep = viewportHeight * 0.8;
  
  // Scroll down in steps
  for (let scrollPos = 0; scrollPos < scrollHeight; scrollPos += scrollStep) {
    window.scrollTo({ top: scrollPos, behavior: 'smooth' });
    await sleep(300);
  }
  
  // Scroll to bottom
  window.scrollTo({ top: scrollHeight, behavior: 'smooth' });
  await sleep(500);
  
  // Scroll back to top
  window.scrollTo({ top: 0, behavior: 'smooth' });
  await sleep(300);
  
  log(`Scrolled page (height: ${scrollHeight}px)`);
}

/**
 * Extract text content safely
 */
function getText(element) {
  if (!element) return '';
  return (element.textContent || element.innerText || '').trim();
}

/**
 * Adaptive element finder
 */
function findElement(strategies) {
  for (const selector of strategies) {
    try {
      const el = document.querySelector(selector);
      if (el) return el;
    } catch (e) {}
  }
  return null;
}

function findElements(strategies) {
  for (const selector of strategies) {
    try {
      const els = document.querySelectorAll(selector);
      if (els.length > 0) return Array.from(els);
    } catch (e) {}
  }
  return [];
}

/**
 * Check if current page is a product detail page
 */
function isDetailPage() {
  const url = window.location.href;
  // PDD detail/edit page patterns
  return url.includes('/goods/goods_detail') || 
         url.includes('/goods/detail') ||
         url.includes('/goods/goods_add') ||
         url.includes('type=edit') ||
         url.includes('goods_id=');
}

/**
 * Check if current page is the product list page
 */
function isListPage() {
  const url = window.location.href;
  // Exclude detail/edit pages first
  if (url.includes('/goods/goods_add') || 
      url.includes('/goods/goods_detail') ||
      url.includes('type=edit') ||
      url.includes('goods_id=')) {
    return false;
  }
  return url.includes('/goods/goods_list') || 
         url.includes('/goods-list') ||
         url.includes('/goods_manage') ||
         document.querySelector('table tbody tr [class*="goods-name"]');
}

/**
 * Extract product list from current page (only checked rows)
 * Returns array of product info with title link elements
 */
function extractCheckedProducts() {
  const products = [];
  
  // Try multiple selectors for product rows
  const productRows = findElements([
    'tr[class*="ant-table-row"]',
    '[class*="goods-item"]',
    '[class*="product-item"]',
    'table tbody tr',
  ]);
  
  log(`Found ${productRows.length} product rows on page`);
  
  // Filter to only checked rows
  const checkedRows = productRows.filter(row => {
    const tr = row.closest('tr') || row;
    // Skip header rows
    if (tr.closest('thead') || tr.querySelector('th')) {
      return false;
    }
    
    // Strategy 1: Row-level selection class (Ant Design table row selection)
    if (tr.classList.contains('ant-table-row-selected') || 
        tr.className.includes('row-selected') ||
        tr.className.includes('selected')) {
      return true;
    }
    
    // Strategy 2: Check for checked checkbox anywhere in the row (not just first cell)
    const rowCheckbox = tr.querySelector(
      'input[type="checkbox"]:checked, ' +
      '.ant-checkbox-checked, ' +
      '.ant-checkbox-wrapper-checked, ' +
      '[class*="checkbox-checked"], ' +
      '[class*="Checkbox"][class*="checked"], ' +
      '[class*="check-box"][class*="active"], ' +
      '[class*="checkbox"][class*="active"]'
    );
    if (rowCheckbox) return true;
    
    // Strategy 3: Look specifically in the first cell
    const firstCell = tr.querySelector('td:first-child, td');
    if (firstCell) {
      const checkbox = firstCell.querySelector(
        'input[type="checkbox"]:checked, ' +
        '.ant-checkbox-checked, ' +
        '.ant-checkbox-wrapper-checked, ' +
        '[class*="checkbox-checked"]'
      );
      if (checkbox) return true;
      
      // Check for checked state via aria attribute
      const ariaChecked = firstCell.querySelector('[aria-checked="true"], [role="checkbox"][aria-checked="true"]');
      if (ariaChecked) return true;
    }
    
    return false;
  });
  
  if (checkedRows.length === 0) {
    log('No products checked', 'warn');
    return [];
  }
  
  log(`Found ${checkedRows.length} checked products`);
  
  checkedRows.forEach((row, index) => {
    try {
      // Find the title link or preview button (red arrow in user's image)
      // PDD new page structure: product name is NOT a link, use "预览" button instead
      let titleLink = null;
      let productName = '';
      
      // First try to find product name element (for display purposes)
      const nameEl = row.querySelector(
        '[class*="goods-name"], [class*="GoodsName"], [class*="goodsName"], ' +
        '[class*="product-name"], [class*="ProductName"], [class*="productName"], ' +
        '[class*="title"], [class*="Title"]'
      );
      if (nameEl) {
        productName = getText(nameEl);
      }
      
      // Strategy 1: Find direct link to goods detail
      titleLink = row.querySelector(
        'a[href*="goods_detail"], ' +
        'a[href*="goods"][class*="name"], ' +
        'a[href*="goods"][class*="title"], ' +
        '[class*="goods-name"] a, ' +
        '[class*="product-name"] a'
      );
      
      // Strategy 2: Find "预览" (preview) button - this opens product detail
      if (!titleLink) {
        const allLinks = row.querySelectorAll('a');
        for (const link of allLinks) {
          const text = link.textContent.trim();
          if (text === '预览' || text === '查看' || text === '详情') {
            titleLink = link;
            log(`Row ${index}: Using "${text}" button as entry point`);
            break;
          }
        }
      }
      
      // Strategy 3: Find "编辑" (edit) button as fallback
      if (!titleLink) {
        const allLinks = row.querySelectorAll('a');
        for (const link of allLinks) {
          const text = link.textContent.trim();
          if (text === '编辑') {
            titleLink = link;
            log(`Row ${index}: Using "编辑" button as entry point`);
            break;
          }
        }
      }
      
      // Strategy 4: Find any link with substantial text (product name)
      if (!titleLink) {
        const cells = row.querySelectorAll('td');
        for (const cell of cells) {
          if (cell === cells[0]) continue; // Skip checkbox cell
          const link = cell.querySelector('a[href]');
          if (link && link.textContent.trim().length > 5) {
            titleLink = link;
            break;
          }
        }
      }
      
      // If still no link, try to get product name from any text element
      if (!productName) {
        // Look for text in image cell or name cell (usually 2nd or 3rd column)
        const cells = row.querySelectorAll('td');
        for (let i = 1; i < Math.min(cells.length, 4); i++) {
          const text = getText(cells[i]);
          if (text.length > 5 && !['修改', '设置', '营销', '编辑', '下架', '预览'].some(k => text.startsWith(k))) {
            productName = text.split('\n')[0].trim(); // Take first line
            break;
          }
        }
      }
      
      if (!titleLink) {
        // Debug: log what we can find in the row
        const allLinks = row.querySelectorAll('a');
        const linkInfo = Array.from(allLinks).slice(0, 5).map(l => `${l.textContent.substring(0,10)}`).join(', ');
        log(`Row ${index}: No entry point found. Links: ${linkInfo || 'none'}. Name: ${productName || 'unknown'}`, 'warn');
        return;
      }
      
      // Extract product ID from URL, row data, or displayed text
      let productId = '';
      if (titleLink.href) {
        const idMatch = titleLink.href.match(/[?&](?:goods_id|id)=(\d+)/);
        if (idMatch) productId = idMatch[1];
      }
      if (!productId) {
        productId = row.dataset.goodsId || row.dataset.id || '';
      }
      // Extract ID from visible text like "ID: 905358822788"
      if (!productId) {
        const rowText = row.textContent || '';
        const textIdMatch = rowText.match(/ID[：:]\s*(\d{6,})/);
        if (textIdMatch) productId = textIdMatch[1];
      }
      if (!productId) {
        productId = `pdd_${index}`;
      }
      
      // Use extracted product name, or fallback to link text
      const name = productName || getText(titleLink) || '未知商品';
      
      const priceEl = row.querySelector('[class*="price"]');
      const price = priceEl ? getText(priceEl).replace(/[^\d.]/g, '') : '0';
      
      const stockEl = row.querySelector('[class*="stock"], [class*="inventory"]');
      const stock = stockEl ? getText(stockEl).replace(/[^\d]/g, '') : '0';
      
      const imgEl = row.querySelector('img');
      const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';
      
      // Extract internal ID from table row (Ant Design data-row-key or other attributes)
      const tr = row.closest('tr') || row;
      let internalId = tr.getAttribute('data-row-key') || tr.dataset.rowKey || tr.dataset.id || '';
      
      // Also find the "编辑" (edit) link's full URL for direct navigation fallback
      let editLinkHref = '';
      const allRowLinks = row.querySelectorAll('a');
      for (const link of allRowLinks) {
        const text = link.textContent.trim();
        if (text === '编辑') {
          // Try getAttribute('href') - works even for relative paths
          const rawHref = link.getAttribute('href');
          if (rawHref && rawHref !== '#' && rawHref !== 'javascript:void(0)' && rawHref.length > 5) {
            try {
              editLinkHref = new URL(rawHref, window.location.origin).href;
            } catch (e) {
              editLinkHref = rawHref;
            }
            // Also extract internal ID from the href if available
            if (!internalId) {
              const idMatch = rawHref.match(/[?&]id=(\d+)/);
              if (idMatch) internalId = idMatch[1];
            }
          }
          break;
        }
      }
      
      log(`Row ${index}: data-row-key="${tr.getAttribute('data-row-key') || 'none'}", internalId="${internalId || 'none'}", editHref="${editLinkHref ? editLinkHref.substring(0, 60) : 'none'}"`);
      
      products.push({
        platform_product_id: productId,
        name: name,
        price: parseFloat(price) || 0,
        stock: parseInt(stock) || 0,
        image_url: imageUrl,
        detail_url: titleLink.href || '',
        platform: PLATFORM_ID,
        rowIndex: index,
        titleLinkHref: titleLink.href || '',
        editLinkHref: editLinkHref,
        internalId: internalId
      });
      
      log(`Row ${index}: [ID:${productId}] [internal:${internalId || '?'}] ${name.substring(0, 30)}... -> ${(editLinkHref || titleLink.href || 'click').substring(0, 60)}...`);
      
    } catch (e) {
      log(`Error extracting row ${index}: ${e.message}`, 'error');
    }
  });
  
  return products;
}

/**
 * Click on the Nth checked product's entry point (preview/edit button)
 * Async with retry mechanism to wait for table to fully render after goBack()
 */
async function clickProductTitle(productInfo) {
  // First try by href if available (instant, no wait needed)
  if (productInfo.titleLinkHref) {
    const allLinks = document.querySelectorAll('a[href]');
    for (const link of allLinks) {
      if (link.href === productInfo.titleLinkHref) {
        log(`Clicking link: ${productInfo.titleLinkHref.substring(0, 60)}...`);
        link.click();
        return true;
      }
    }
  }
  
  // Navigate to the correct page first (in case goBack() reset the pagination)
  if (state.currentPageNumber > 1) {
    const currentPage = getCurrentPageNumber();
    if (currentPage !== state.currentPageNumber) {
      log(`Page changed from ${state.currentPageNumber} to ${currentPage}, navigating back...`);
      await navigateToPage(state.currentPageNumber);
      await sleep(1000); // Wait for table to reload
    }
  }
  
  // Retry loop: wait for table rows to appear and find product
  const maxRetries = 15;
  let hasScrolled = false;
  let hasCheckedPageSize = false;
  for (let retry = 0; retry < maxRetries; retry++) {
    // After a few retries, check if page size was reset (critical for 200/page users)
    if (retry === 5 && !hasCheckedPageSize && state.pageSize && state.pageSize > 10) {
      hasCheckedPageSize = true;
      const currentSize = getCurrentPageSize();
      if (currentSize !== state.pageSize) {
        log(`Page size changed from ${state.pageSize} to ${currentSize}, product may be on different page. Restoring...`);
        const restored = await setPageSize(state.pageSize);
        if (restored) {
          await sleep(1500); // Wait for table to reload with new page size
          log('Page size restored, continuing search...');
        }
      }
    }
    
    // After a few retries, scroll down the table to reveal more rows (lazy-loaded/virtual scroll)
    if (retry === 3 && !hasScrolled) {
      hasScrolled = true;
      log('Product not found in visible rows, scrolling table to load more...');
      const tableBody = document.querySelector('.ant-table-body, .ant-table-content, [class*="table-body"]');
      if (tableBody && tableBody.scrollHeight > tableBody.clientHeight) {
        // Virtual-scroll table: scroll its container to the bottom
        for (let pos = 0; pos < tableBody.scrollHeight; pos += 300) {
          tableBody.scrollTop = pos;
          await sleep(200);
        }
        tableBody.scrollTop = 0;
        await sleep(500);
      } else {
        // Standard page: scroll the full page down and back
        for (let pos = 0; pos < document.documentElement.scrollHeight; pos += 500) {
          window.scrollTo(0, pos);
          await sleep(150);
        }
        window.scrollTo(0, 0);
        await sleep(500);
      }
    }
    // Strategy 1: Find by checked row index (works on first load when checkboxes are still checked)
    const productRows = document.querySelectorAll('tr[class*="ant-table-row"], table tbody tr');
    const checkedRows = Array.from(productRows).filter(row => {
      const tr = row.closest('tr') || row;
      if (tr.closest('thead') || tr.querySelector('th')) return false;
      if (tr.classList.contains('ant-table-row-selected') || 
          tr.className.includes('row-selected') ||
          tr.className.includes('selected')) {
        return true;
      }
      const rowCheckbox = tr.querySelector(
        'input[type="checkbox"]:checked, .ant-checkbox-checked, ' +
        '.ant-checkbox-wrapper-checked, [class*="checkbox-checked"], ' +
        '[aria-checked="true"]'
      );
      if (rowCheckbox) return true;
      return false;
    });
    
    if (productInfo.rowIndex < checkedRows.length) {
      const row = checkedRows[productInfo.rowIndex];
      const allLinks = row.querySelectorAll('a');
      for (const link of allLinks) {
        const text = link.textContent.trim();
        if (text === '预览' || text === '查看' || text === '详情' || text === '编辑') {
          log(`Clicking "${text}" button in checked row ${productInfo.rowIndex}`);
          link.click();
          return true;
        }
      }
    }
    
    // Strategy 2: Find row by product ID in text (works after goBack when checkboxes unchecked)
    if (productInfo.platform_product_id && !productInfo.platform_product_id.startsWith('pdd_')) {
      const allRows = document.querySelectorAll('tr[class*="ant-table-row"], table tbody tr');
      for (const row of allRows) {
        const tr = row.closest('tr') || row;
        if (tr.closest('thead') || tr.querySelector('th')) continue;
        const rowText = row.textContent || '';
        if (rowText.includes(productInfo.platform_product_id)) {
          const links = row.querySelectorAll('a');
          for (const link of links) {
            const text = link.textContent.trim();
            if (text === '预览' || text === '查看' || text === '详情' || text === '编辑') {
              log(`Found product by ID on retry ${retry}, clicking "${text}" button`);
              link.click();
              return true;
            }
          }
        }
      }
      
      if (retry === 0) {
        log(`Product ${productInfo.platform_product_id} not found in DOM yet, waiting for table to load... (${allRows.length} rows visible)`);
      }
    }
    
    // Strategy 3: Find by product name (partial match)
    if (productInfo.name && productInfo.name.length > 5) {
      const namePrefix = productInfo.name.substring(0, 15);
      const allRows = document.querySelectorAll('tr[class*="ant-table-row"], table tbody tr');
      for (const row of allRows) {
        const tr = row.closest('tr') || row;
        if (tr.closest('thead') || tr.querySelector('th')) continue;
        if ((row.textContent || '').includes(namePrefix)) {
          const links = row.querySelectorAll('a');
          for (const link of links) {
            const text = link.textContent.trim();
            if (text === '预览' || text === '查看' || text === '详情' || text === '编辑') {
              log(`Found product by name on retry ${retry}, clicking "${text}" button`);
              link.click();
              return true;
            }
          }
        }
      }
    }
    
    // Wait before next retry
    await sleep(1000);
  }
  
  // All retries exhausted - try stored URL as last resort
  const targetUrl = productInfo.editLinkHref || productInfo.titleLinkHref || productInfo.detail_url;
  if (targetUrl && targetUrl.startsWith('http')) {
    log(`Navigating to stored URL after retries: ${targetUrl.substring(0, 80)}...`);
    window.location.href = targetUrl;
    return true;
  }
  
  // Fallback: use detail URL template if available (replace goods_id)
  if (state.detailUrlTemplate && productInfo.platform_product_id) {
    // We don't have INTERNAL_ID, but try navigating with just goods_id
    // PDD may redirect or still load the page with just goods_id
    let directUrl = state.detailUrlTemplate
      .replace('{GOODS_ID}', productInfo.platform_product_id)
      .replace(/[?&]id=\{INTERNAL_ID\}/, ''); // Remove internal ID param
    // Fix URL if first param was removed (& should become ?)
    directUrl = directUrl.replace(/\?&/, '?').replace(/([^?])&/, '$1?');
    if (directUrl && directUrl.startsWith('http')) {
      log(`Attempting direct URL navigation (template fallback): ${directUrl.substring(0, 80)}...`);
      window.location.href = directUrl;
      return true;
    }
  }
  
  // Last resort: try to find product on next pagination page
  const nextPageBtn = document.querySelector(
    '.ant-pagination-next:not(.ant-pagination-disabled), ' +
    '[class*="pagination"] .next:not(.disabled), ' +
    '.ant-pagination-item-active + .ant-pagination-item'
  );
  if (nextPageBtn) {
    log(`Product not found on current page, trying next page...`);
    nextPageBtn.click();
    await sleep(2000);
    // Recursive retry on the new page (single attempt)
    const allRows = document.querySelectorAll('tr[class*="ant-table-row"], table tbody tr');
    for (const row of allRows) {
      const tr = row.closest('tr') || row;
      if (tr.closest('thead') || tr.querySelector('th')) continue;
      if ((row.textContent || '').includes(productInfo.platform_product_id)) {
        const links = row.querySelectorAll('a');
        for (const link of links) {
          const text = link.textContent.trim();
          if (text === '预览' || text === '查看' || text === '详情' || text === '编辑') {
            log(`Found product on next page, clicking "${text}" button`);
            link.click();
            return true;
          }
        }
      }
    }
  }
  
  log(`Could not find clickable element for product [ID:${productInfo.platform_product_id}] after ${maxRetries} retries`, 'error');
  return false;
}

/**
 * Extract product meta info (ID, stock, SKU) from detail page URL and DOM
 */
function extractDetailPageMeta() {
  const result = { productId: '', stock: '', sku: '' };
  
  // 1. Extract product ID from current page URL
  const url = window.location.href;
  const urlIdMatch = url.match(/[?&](?:goods_id|id|goodsId)=(\d+)/);
  if (urlIdMatch) {
    result.productId = urlIdMatch[1];
  }
  
  // 2. Extract product ID from page text (e.g., "ID: 905358822788" or "商品ID: XXX")
  if (!result.productId) {
    const pageText = document.body.textContent || '';
    const textIdMatch = pageText.match(/(?:商品)?ID[：:]\s*(\d{6,})/);
    if (textIdMatch) result.productId = textIdMatch[1];
  }
  
  // 3. Extract product ID from DOM elements with specific labels
  if (!result.productId) {
    const allElements = document.querySelectorAll('span, div, td, p, label');
    for (const el of allElements) {
      const text = (el.textContent || '').trim();
      if (text.match(/^ID[：:]\s*\d{6,}$/)) {
        const m = text.match(/(\d{6,})/);
        if (m) { result.productId = m[1]; break; }
      }
    }
  }
  
  // 4. Extract stock from page - look for labels like "库存", "总库存"
  const stockPatterns = [
    /(?:总?库存|stock)[：:]\s*(\d+)/i,
    /(?:剩余|可售)[：:]\s*(\d+)/i,
  ];
  const bodyText = document.body.textContent || '';
  for (const pat of stockPatterns) {
    const m = bodyText.match(pat);
    if (m) { result.stock = m[1]; break; }
  }
  
  // 5. Extract stock from input/span near "库存" label
  if (!result.stock) {
    const labels = document.querySelectorAll('label, span, div, td');
    for (const label of labels) {
      const lt = (label.textContent || '').trim();
      if (lt === '库存' || lt === '总库存') {
        // Check next sibling or parent's next element for the value
        const parent = label.closest('div, tr, td, li');
        if (parent) {
          const input = parent.querySelector('input');
          if (input && input.value) { result.stock = input.value; break; }
          const valueEl = parent.querySelector('span, div, td');
          if (valueEl && valueEl !== label) {
            const numMatch = valueEl.textContent.match(/(\d+)/);
            if (numMatch) { result.stock = numMatch[1]; break; }
          }
        }
      }
    }
  }
  
  // 6. Extract SKU
  const skuMatch = bodyText.match(/SKU[：:]\s*([^\s\n,，]{1,50})/i);
  if (skuMatch && skuMatch[1] !== '无') result.sku = skuMatch[1];
  
  log(`Detail page meta - ID: ${result.productId || 'not found'}, Stock: ${result.stock || 'not found'}, SKU: ${result.sku || 'not found'}`);
  return result;
}

/**
 * Extract product detail from current detail page
 * Extracts: 商品轮播图, 商品标题, 商品详情, 规格与库存, 价格及库存, 服务与承诺
 */
async function extractDetailPageContent() {
  log('Extracting detail page content...');
  
  // First scroll the page to load lazy content
  await scrollPage();
  await sleep(800);
  
  const detail = {
    description: '',
    specs: {},
    images: [],
    title: '',
    price: '',
    stock: '',
    services: ''
  };
  
  // ===== 1. Extract product title (商品标题) =====
  const titleEl = findElement([
    '[class*="goods-name"]',
    '[class*="goods_name"]',
    '[class*="goodsName"]',
    '[class*="product-name"]',
    '[class*="productName"]',
    '[class*="title"]',
    'h1', 'h2'
  ]);
  detail.title = getText(titleEl);
  log(`Title: ${detail.title.substring(0, 50)}...`);
  
  // ===== 2. Extract product images (商品轮播图) =====
  const images = findElements([
    '[class*="gallery"] img',
    '[class*="slider"] img',
    '[class*="carousel"] img',
    '[class*="goods-img"] img',
    '[class*="product-img"] img',
    '[class*="main-image"] img',
    '[class*="preview"] img',
    'img[src*="pddpic"]',
    'img[src*="pinduoduo"]',
    'img[src*="img.pddpic"]',
  ]);
  images.forEach(img => {
    const src = img.src || img.dataset.src || img.getAttribute('data-origin');
    if (src && src.startsWith('http') && !detail.images.includes(src)) {
      detail.images.push(src);
    }
  });
  log(`Images: ${detail.images.length} found`);
  
  // ===== 3. Extract price and stock (价格及库存) =====
  const priceEl = findElement([
    '[class*="price"]',
    '[class*="Price"]',
    'span[class*="price"]',
    'div[class*="price"]'
  ]);
  detail.price = getText(priceEl);
  
  const stockEl = findElement([
    '[class*="stock"]',
    '[class*="Stock"]',
    '[class*="inventory"]',
    '[class*="Inventory"]'
  ]);
  detail.stock = getText(stockEl);
  
  // ===== 4. Extract specifications (规格与库存) =====
  // Look for spec tables or lists
  const specSections = findElements([
    '[class*="spec"]',
    '[class*="Spec"]',
    '[class*="sku"]',
    '[class*="Sku"]',
    '[class*="attr"]',
    '[class*="property"]',
    'table tr',
  ]);
  
  specSections.forEach(section => {
    // Try to find label-value pairs
    const labels = section.querySelectorAll('[class*="label"], [class*="name"], th, td:first-child');
    const values = section.querySelectorAll('[class*="value"], [class*="content"], td:last-child');
    
    if (labels.length > 0 && values.length > 0) {
      for (let i = 0; i < Math.min(labels.length, values.length); i++) {
        const label = getText(labels[i]);
        const value = getText(values[i]);
        if (label && value && label !== value && label.length < 50) {
          detail.specs[label] = value;
        }
      }
    } else {
      // Try to parse text content
      const text = getText(section);
      const match = text.match(/^([^:：]+)[：:]\s*(.+)$/);
      if (match) {
        detail.specs[match[1].trim()] = match[2].trim();
      }
    }
  });
  
  // ===== 5. Extract product description (商品详情) =====
  const descEl = findElement([
    '[class*="goods-desc"]',
    '[class*="goods_desc"]',
    '[class*="goodsDesc"]',
    '[class*="product-desc"]',
    '[class*="description"]',
    '[class*="detail-content"]',
    '[class*="detail_content"]',
    '[class*="detailContent"]',
    '[class*="goods-info"]',
    '[class*="info-section"]',
  ]);
  if (descEl) {
    detail.description = getText(descEl).substring(0, 5000);
  }
  
  // ===== 6. Extract services (服务与承诺) =====
  const serviceEl = findElement([
    '[class*="service"]',
    '[class*="Service"]',
    '[class*="promise"]',
    '[class*="Promise"]',
    '[class*="guarantee"]',
    '[class*="Guarantee"]',
  ]);
  if (serviceEl) {
    detail.services = getText(serviceEl).substring(0, 500);
  }
  
  // Build full description from all extracted content
  let fullDescription = '';
  if (detail.title) fullDescription += `商品名称: ${detail.title}\n\n`;
  if (detail.price) fullDescription += `价格: ${detail.price}\n`;
  if (detail.stock) fullDescription += `库存: ${detail.stock}\n\n`;
  if (Object.keys(detail.specs).length > 0) {
    fullDescription += '规格参数:\n';
    for (const [k, v] of Object.entries(detail.specs)) {
      fullDescription += `  ${k}: ${v}\n`;
    }
    fullDescription += '\n';
  }
  if (detail.services) fullDescription += `服务承诺: ${detail.services}\n\n`;
  if (detail.description) fullDescription += `商品详情:\n${detail.description}\n`;
  
  // If description is still empty, extract all text from page
  if (fullDescription.length < 100) {
    const mainContent = findElement([
      '[class*="detail"]',
      '[class*="content"]',
      'main',
      '#app',
      'body'
    ]);
    if (mainContent) {
      fullDescription = getText(mainContent).substring(0, 5000);
    }
  }
  
  detail.description = fullDescription;
  
  log(`Extracted: description(${detail.description.length} chars), specs(${Object.keys(detail.specs).length}), images(${detail.images.length})`);
  
  return detail;
}

/**
 * Main extraction process - Phase 1: Get list of checked products
 */
async function startExtraction() {
  if (state.isExtracting) {
    log('Extraction already in progress', 'warn');
    return;
  }
  
  state.isExtracting = true;
  state.extractedProducts = [];
  state.pendingProducts = [];
  state.currentProductIndex = 0;
  state.listPageUrl = window.location.href;
  state.currentPageNumber = getCurrentPageNumber();
  
  log('Starting product extraction...');
  log(`List page URL: ${state.listPageUrl}`);
  ipcRenderer.send('learning:started', { platform: PLATFORM_ID });
  
  // Wait for pagination component to fully load
  log('Waiting for pagination to load...');
  await sleep(1000);
  
  // Get total product count first
  let totalCount = getTotalProductCount();
  log(`Total products in list: ${totalCount || 'unknown'}`);
  
  // Determine optimal page size based on total count
  // Default to 50 if we can't detect total count
  let targetPageSize = 50;
  if (totalCount) {
    targetPageSize = getOptimalPageSize(totalCount);
  }
  
  // ALWAYS force set page size to ensure all products are visible (核心校准步骤)
  log(`Forcing page size to ${targetPageSize} to ensure all products are visible...`);
  ipcRenderer.send('learning:progress', {
    platform: PLATFORM_ID,
    phase: 'preparing',
    message: `正在调整单页显示数量为 ${targetPageSize}，确保显示全部商品...`
  });
  
  const adjusted = await setPageSize(targetPageSize);
  if (adjusted) {
    state.pageSize = targetPageSize;
    await sleep(1500); // Wait for table to reload
    log(`Page size set to ${targetPageSize}`);
  } else {
    // Fallback: try to detect current page size
    state.pageSize = getCurrentPageSize();
    log(`Could not set page size, using detected: ${state.pageSize}`, 'warn');
  }
  
  log(`Current page number: ${state.currentPageNumber}, page size: ${state.pageSize}`);
  
  try {
    // Extract checked products from list page
    const products = extractCheckedProducts();
    
    if (products.length === 0) {
      ipcRenderer.send('learning:error', {
        platform: PLATFORM_ID,
        error: '请先勾选需要学习的商品，再点击开始学习'
      });
      state.isExtracting = false;
      await ipcRenderer.invoke('learning:clear-state', PLATFORM_ID);
      return;
    }
    
    state.pendingProducts = products;
    state.totalProducts = products.length;
    
    // Sync state to main process
    await syncStateToMain();
    
    log(`Found ${products.length} products to learn`);
    
    // Send progress update
    ipcRenderer.send('learning:progress', {
      platform: PLATFORM_ID,
      phase: 'listing',
      extracted: products.length,
      message: `已识别 ${products.length} 个商品，开始获取详情...`
    });
    
    // Start processing first product - click its title
    await sleep(500);
    processNextProduct();
    
  } catch (error) {
    log(`Extraction error: ${error.message}`, 'error');
    ipcRenderer.send('learning:error', {
      platform: PLATFORM_ID,
      error: error.message
    });
    state.isExtracting = false;
    await ipcRenderer.invoke('learning:clear-state', PLATFORM_ID);
  }
}

/**
 * Schedule processNextProduct with dedup guard
 */
function scheduleNextProduct(delay = 800) {
  if (_processingScheduled) {
    log('processNextProduct already scheduled, skipping duplicate');
    return;
  }
  _processingScheduled = true;
  setTimeout(() => {
    _processingScheduled = false;
    if (state.isExtracting) {
      processNextProduct();
    }
  }, delay);
}

/**
 * Process next product in the queue
 */
async function processNextProduct() {
  if (!state.isExtracting) {
    log('Extraction stopped');
    return;
  }
  
  // Verify we're on the list page before trying to find products
  if (!isListPage()) {
    log('Not on list page yet, waiting for navigation...');
    // Retry after delay - page might still be navigating
    setTimeout(() => {
      if (state.isExtracting && isListPage()) {
        processNextProduct();
      } else if (state.isExtracting) {
        log('Still not on list page, requesting navigation to list page');
        if (state.listPageUrl) {
          window.location.href = state.listPageUrl;
        }
      }
    }, 3000);
    return;
  }
  
  if (state.currentProductIndex >= state.pendingProducts.length) {
    // All done
    log('All products processed, sending to backend');
    ipcRenderer.send('learning:products-extracted', {
      platform: PLATFORM_ID,
      products: state.extractedProducts,
      totalCount: state.extractedProducts.length
    });
    state.isExtracting = false;
    await ipcRenderer.invoke('learning:clear-state', PLATFORM_ID);
    return;
  }
  
  const product = state.pendingProducts[state.currentProductIndex];
  log(`Processing product ${state.currentProductIndex + 1}/${state.totalProducts}: [ID:${product.platform_product_id}] ${product.name.substring(0, 30)}...`);
  
  // Send progress
  ipcRenderer.send('learning:progress', {
    platform: PLATFORM_ID,
    phase: 'detail',
    current: state.currentProductIndex + 1,
    total: state.totalProducts,
    productName: product.name,
    message: `正在学习商品详情 (${state.currentProductIndex + 1}/${state.totalProducts}): ${product.name.substring(0, 25)}...`
  });
  
  // Sync state before navigating
  await syncStateToMain();
  
  // Click the product entry point (preview/edit button)
  // clickProductTitle is async - it retries until table is loaded
  if (!(await clickProductTitle(product))) {
    // Failed to click after all retries, skip this product
    log(`Skipping product ${state.currentProductIndex + 1} - could not click entry point after retries`);
    state.currentProductIndex++;
    await syncStateToMain();
    setTimeout(processNextProduct, 500);
  }
  // After click, page will navigate. handleDetailPage will be called on new page load
}

/**
 * Handle detail page - extract content using vision model and go back
 */
async function handleDetailPage() {
  if (!state.isExtracting || state.currentProductIndex >= state.pendingProducts.length) {
    log('Not in extraction mode or no more products');
    return;
  }
  
  // Guard against double-invocation
  if (_detailHandled && state.isOnDetailPage) {
    log('Detail page already being handled, skipping duplicate call');
    return;
  }
  _detailHandled = true;
  
  log('Detail page loaded, starting comprehensive extraction...');
  state.isOnDetailPage = true;
  
  // Capture URL template from the first successful detail page navigation
  // This lets us construct correct URLs for products not in DOM (page 2+)
  // PDD edit URL has two IDs: ?id={INTERNAL_ID}&goods_id={GOODS_ID}&type=edit
  const currentPageUrl = window.location.href;
  if (!state.detailUrlTemplate) {
    // Replace goods_id= first (more specific, won't match standalone id=)
    let templateUrl = currentPageUrl.replace(/([?&]goods_id=)\d+/, '$1{GOODS_ID}');
    // Replace standalone ?id= or &id= (the [?&] ensures we don't re-match goods_id)
    templateUrl = templateUrl.replace(/([?&])id=\d+/, '$1id={INTERNAL_ID}');
    if (templateUrl !== currentPageUrl && templateUrl.includes('{GOODS_ID}')) {
      state.detailUrlTemplate = templateUrl;
      log(`Captured detail URL template: ${state.detailUrlTemplate}`);
      await syncStateToMain();
    } else {
      log(`Could not extract URL template from: ${currentPageUrl}`);
    }
  }
  
  const product = state.pendingProducts[state.currentProductIndex];
  
  try {
    // Wait for page to fully load
    await sleep(1000);
    
    // Step 0: Extract product ID and stock from detail page URL and DOM
    log('Step 0: Extracting product ID and stock from detail page...');
    const detailPageInfo = extractDetailPageMeta();
    if (detailPageInfo.productId && (!product.platform_product_id || product.platform_product_id.startsWith('pdd_'))) {
      product.platform_product_id = detailPageInfo.productId;
      log(`Updated product ID from detail page: ${detailPageInfo.productId}`);
    }
    if (detailPageInfo.stock) {
      product.stock = parseInt(detailPageInfo.stock) || product.stock;
      log(`Updated stock from detail page: ${detailPageInfo.stock}`);
    }
    if (detailPageInfo.sku) {
      product.sku = detailPageInfo.sku;
      log(`Updated SKU from detail page: ${detailPageInfo.sku}`);
    }
    
    // Step 1: Slowly scroll through entire page to load ALL images
    log('Step 1: Loading all images by slow scrolling...');
    await scrollPageSlowly();
    await sleep(500);
    
    // Step 2: Request multi-segment vision analysis of the whole page
    log('Step 2: Performing multi-segment vision analysis...');
    let detail = null;
    try {
      detail = await extractWithMultiSegmentVision();
    } catch (visionErr) {
      log(`Vision extraction failed: ${visionErr.message}, falling back to DOM extraction`, 'warn');
    }
    
    // Step 3: Click and analyze each product image in detail
    log('Step 3: Analyzing individual product images...');
    let imageAnalysis = '';
    try {
      imageAnalysis = await analyzeAllEnlargedImages();
    } catch (imgErr) {
      log(`Image analysis failed: ${imgErr.message}`, 'warn');
    }
    
    // Fallback to DOM-based extraction if vision failed
    if (!detail || !detail.description || detail.description.length < 100) {
      log('Vision result insufficient, supplementing with DOM extraction');
      const domDetail = await extractDetailPageContent();
      if (!detail) detail = domDetail;
      else {
        // Merge DOM extraction with vision results
        if (domDetail.description && domDetail.description.length > detail.description.length) {
          detail.description += '\n\n' + domDetail.description;
        }
        detail.specs = { ...domDetail.specs, ...detail.specs };
        detail.images = [...new Set([...(detail.images || []), ...(domDetail.images || [])])];
      }
    }
    
    // Append detailed image analysis to description
    if (imageAnalysis && imageAnalysis.length > 50) {
      detail.description = detail.description + '\n\n===== 商品图片详细信息 =====\n' + imageAnalysis;
      log(`Added ${imageAnalysis.length} chars of image analysis to description`);
    }
    
    // Merge with basic product info
    const fullProduct = {
      ...product,
      description: detail.description,
      specs: detail.specs || {},
      images: detail.images || []
    };
    
    // Remove helper properties
    delete fullProduct.rowIndex;
    delete fullProduct.titleLinkHref;
    
    state.extractedProducts.push(fullProduct);
    log(`Product ${state.currentProductIndex + 1} [ID:${product.platform_product_id}] extracted successfully (${detail.description.length} chars)`);
    
  } catch (err) {
    log(`Error extracting detail: ${err.message}`, 'error');
    // Still add the product with basic info
    state.extractedProducts.push({
      ...product,
      description: '',
      specs: {}
    });
  }
  
  // Move to next product
  state.currentProductIndex++;
  state.isOnDetailPage = false;
  _detailHandled = false;  // Reset guard for next detail page
  
  // Sync state to main
  await syncStateToMain();
  
  // Go back to list page
  log('Going back to list page...');
  
  // Notify main process to navigate back
  ipcRenderer.send('learning:navigate-back', {
    platform: PLATFORM_ID,
    listPageUrl: state.listPageUrl,
    nextIndex: state.currentProductIndex,
    total: state.totalProducts
  });
}

/**
 * Slowly scroll through entire page to ensure all images load
 */
async function scrollPageSlowly() {
  const scrollHeight = document.documentElement.scrollHeight;
  const viewportHeight = window.innerHeight;
  const scrollStep = viewportHeight * 0.8; // Larger steps for speed
  
  log(`Slow scrolling page (height: ${scrollHeight}px)...`);
  
  // Scroll to top first
  window.scrollTo({ top: 0 });
  await sleep(200);
  
  // Scroll down in larger steps
  for (let scrollPos = 0; scrollPos < scrollHeight; scrollPos += scrollStep) {
    window.scrollTo({ top: scrollPos });
    await sleep(400); // Enough for lazy loading to trigger
  }
  
  // Ensure we're at the very bottom
  window.scrollTo({ top: scrollHeight });
  await sleep(400);
  
  // Scroll back to top
  window.scrollTo({ top: 0 });
  await sleep(200);
  
  log('Page scrolling completed');
}

/**
 * Extract product info using multi-segment vision analysis
 * Takes screenshots of different page sections and analyzes each
 */
async function extractWithMultiSegmentVision() {
  log('Requesting multi-segment vision analysis...');
  
  // Request main process to perform multi-segment analysis
  const result = await ipcRenderer.invoke('learning:vision-analyze-multi-segment', PLATFORM_ID);
  
  if (!result || !result.success) {
    throw new Error(result?.error || 'Multi-segment vision analysis failed');
  }
  
  log(`Multi-segment vision analysis completed: ${result.description?.length || 0} chars`);
  
  return {
    description: result.description || '',
    specs: result.specs || {},
    images: result.images || []
  };
}

/**
 * Find all clickable thumbnail images on the page
 * Returns array of image elements that can be clicked to enlarge
 */
function findClickableImages() {
  const clickableImages = [];
  
  // Strategy 1: Images in carousel/gallery containers
  const carouselImages = document.querySelectorAll(
    '[class*="carousel"] img, ' +
    '[class*="gallery"] img, ' +
    '[class*="swiper"] img, ' +
    '[class*="slider"] img, ' +
    '[class*="thumb"] img, ' +
    '[class*="preview"] img'
  );
  carouselImages.forEach(img => {
    if (img.offsetWidth > 30 && img.offsetHeight > 30) {
      clickableImages.push(img);
    }
  });
  
  // Strategy 2: Images that are direct children of anchor tags or clickable divs
  const linkedImages = document.querySelectorAll(
    'a img, ' +
    '[onclick] img, ' +
    '[class*="click"] img, ' +
    '[class*="zoom"] img'
  );
  linkedImages.forEach(img => {
    if (img.offsetWidth > 50 && img.offsetHeight > 50 && !clickableImages.includes(img)) {
      clickableImages.push(img);
    }
  });
  
  // Strategy 3: Images in product info sections (商品轮播图, 商品详情图)
  const productImages = document.querySelectorAll(
    '[class*="goods"] img, ' +
    '[class*="product"] img, ' +
    '[class*="detail"] img, ' +
    '[class*="info"] img, ' +
    '[class*="main-img"] img, ' +
    '[class*="sku"] img'
  );
  productImages.forEach(img => {
    // Filter: must be reasonably sized (not icons) and not already added
    if (img.offsetWidth >= 60 && img.offsetHeight >= 60 && !clickableImages.includes(img)) {
      // Skip if it's a logo or icon
      const src = img.src || '';
      if (!src.includes('logo') && !src.includes('icon') && !src.includes('avatar')) {
        clickableImages.push(img);
      }
    }
  });
  
  // Strategy 4: Any image that looks like a product image based on size
  const allImages = document.querySelectorAll('img');
  allImages.forEach(img => {
    if (img.offsetWidth >= 80 && img.offsetHeight >= 80 && !clickableImages.includes(img)) {
      const src = img.src || '';
      // Check if it's a substantial content image
      if (!src.includes('logo') && !src.includes('icon') && !src.includes('avatar') && !src.includes('sprite')) {
        // Check if parent is clickable
        const parent = img.parentElement;
        if (parent && (parent.tagName === 'A' || parent.onclick || parent.style.cursor === 'pointer')) {
          clickableImages.push(img);
        }
      }
    }
  });
  
  log(`Found ${clickableImages.length} clickable images on page`);
  return clickableImages;
}

/**
 * Click image to enlarge, analyze, then close
 * Returns analysis result for the enlarged image
 */
async function analyzeEnlargedImage(img, index) {
  log(`Analyzing image ${index + 1}...`);
  
  try {
    // Scroll image into view
    img.scrollIntoView({ behavior: 'instant', block: 'center' });
    await sleep(200);
    
    // Click to enlarge
    const clickTarget = img.parentElement?.tagName === 'A' ? img.parentElement : img;
    clickTarget.click();
    await sleep(800); // Wait for modal/enlarged view to appear
    
    // Check if a modal/overlay appeared
    const modal = document.querySelector(
      '[class*="modal"]:not([style*="display: none"]), ' +
      '[class*="lightbox"]:not([style*="display: none"]), ' +
      '[class*="preview-modal"], ' +
      '[class*="image-viewer"], ' +
      '[class*="zoom-viewer"], ' +
      '[class*="enlarged"], ' +
      '.ant-modal-wrap:not([style*="display: none"]), ' +
      '[class*="overlay"]:not([style*="display: none"])'
    );
    
    let analysisResult = null;
    
    if (modal) {
      log(`Modal detected for image ${index + 1}, capturing enlarged view...`);
      await sleep(500); // Wait for image to fully load in modal
      
      // Request vision analysis of current viewport (which shows the enlarged image)
      try {
        const result = await ipcRenderer.invoke('learning:vision-analyze-page', PLATFORM_ID);
        if (result && result.success) {
          analysisResult = result.description || '';
          log(`Image ${index + 1} analysis: ${analysisResult.substring(0, 100)}...`);
        }
      } catch (visionErr) {
        log(`Vision analysis failed for image ${index + 1}: ${visionErr.message}`, 'warn');
      }
      
      // Try to close the modal
      await closeImageModal(modal);
    } else {
      log(`No modal detected for image ${index + 1}, may have opened in new view`);
      // Still try to analyze current page state
      try {
        const result = await ipcRenderer.invoke('learning:vision-analyze-page', PLATFORM_ID);
        if (result && result.success) {
          analysisResult = result.description || '';
        }
      } catch (visionErr) {
        log(`Vision analysis failed: ${visionErr.message}`, 'warn');
      }
      
      // Try to go back or close any overlay
      await tryCloseOverlay();
    }
    
    await sleep(300);
    return analysisResult;
    
  } catch (err) {
    log(`Error analyzing image ${index + 1}: ${err.message}`, 'error');
    return null;
  }
}

/**
 * Try to close image modal/overlay
 */
async function closeImageModal(modal) {
  // Strategy 1: Click close button
  const closeBtn = modal.querySelector(
    '[class*="close"], ' +
    '[class*="Close"], ' +
    'button[aria-label*="close"], ' +
    'button[aria-label*="Close"], ' +
    '.ant-modal-close, ' +
    '[class*="cancel"]'
  );
  if (closeBtn) {
    log('Clicking close button...');
    closeBtn.click();
    await sleep(300);
    return;
  }
  
  // Strategy 2: Click outside the modal content
  const backdrop = document.querySelector(
    '.ant-modal-mask, ' +
    '[class*="mask"], ' +
    '[class*="backdrop"], ' +
    '[class*="overlay"]'
  );
  if (backdrop) {
    log('Clicking backdrop to close...');
    backdrop.click();
    await sleep(300);
    return;
  }
  
  // Strategy 3: Press Escape key
  log('Pressing Escape to close...');
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
  await sleep(300);
}

/**
 * Try to close any overlay or go back
 */
async function tryCloseOverlay() {
  // Try pressing Escape
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
  await sleep(300);
  
  // Try clicking any visible close button
  const closeButtons = document.querySelectorAll('[class*="close"], .ant-modal-close');
  for (const btn of closeButtons) {
    if (btn.offsetParent !== null) { // Is visible
      btn.click();
      await sleep(300);
      break;
    }
  }
}

/**
 * Analyze all clickable images on the page by enlarging each one
 * Returns combined analysis results
 */
async function analyzeAllEnlargedImages() {
  const images = findClickableImages();
  
  if (images.length === 0) {
    log('No clickable images found to analyze');
    return '';
  }
  
  // Analyze all found images without limit
  log(`Analyzing all ${images.length} images in detail...`);
  
  const analysisResults = [];
  
  for (let i = 0; i < images.length; i++) {
    log(`Processing image ${i + 1}/${images.length}...`);
    const result = await analyzeEnlargedImage(images[i], i);
    if (result && result.length > 20) {
      analysisResults.push(`【图片${i + 1}内容】:\n${result}`);
    }
    
    // Small delay between images
    await sleep(200);
  }
  
  const combined = analysisResults.join('\n\n');
  log(`Completed detailed image analysis: ${analysisResults.length}/${images.length} images analyzed, ${combined.length} chars total`);
  
  return combined;
}

/**
 * Continue processing after returning to list page
 */
async function continueAfterBack() {
  log('Back on list page, continuing...');
  
  // Restore state from main if needed
  if (!state.isExtracting) {
    await loadStateFromMain();
  }
  
  // Check and restore page size if it was reset (critical for 200/page users)
  if (state.pageSize && state.pageSize > 10) {
    await ensurePageSize();
  }
  
  // Use dedup guard to schedule next product
  scheduleNextProduct(500);
}

// IPC Listeners
ipcRenderer.on('learning:start-extraction', () => {
  log('Received start extraction command');
  startExtraction();
});

ipcRenderer.on('learning:continue', () => {
  log('Received continue command');
  continueAfterBack();
});

ipcRenderer.on('learning:stop', () => {
  log('Received stop command');
  state.isExtracting = false;
});

// Initialize - detect page type and handle accordingly
window.addEventListener('DOMContentLoaded', async () => {
  log('Learning preload script loaded');
  log(`Current URL: ${window.location.href}`);
  
  // Reset per-page guards
  _processingScheduled = false;
  _detailHandled = false;
  
  await sleep(500);
  
  // Try to restore state from main process
  const hasState = await loadStateFromMain();
  
  if (hasState && state.isExtracting) {
    // We're in the middle of extraction
    if (isDetailPage()) {
      log('Detected detail page during extraction - will extract content');
      // Small delay then extract
      if (!_detailHandled) {
        _detailHandled = true;
        setTimeout(() => handleDetailPage(), 500);
      }
    } else if (isListPage()) {
      log('Back on list page during extraction - auto-continuing to next product');
      // Check and restore page size first (critical for 200/page users)
      if (state.pageSize && state.pageSize > 10) {
        await ensurePageSize();
      }
      // AUTO-CONTINUE: schedule next product processing immediately
      // (don't rely solely on learning:continue IPC which may not arrive)
      scheduleNextProduct(800);
    } else {
      log('On unknown page during extraction');
    }
  } else {
    log('On list page or not extracting');
  }
  
  ipcRenderer.send('learning:ready', { platform: PLATFORM_ID });
});

// Also check on page visibility change (for SPA navigation)
document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible' && state.isExtracting) {
    if (isDetailPage() && !_detailHandled) {
      _detailHandled = true;
      handleDetailPage();
    } else if (isListPage()) {
      // Ensure page size is restored before continuing (for SPA navigation)
      if (state.pageSize && state.pageSize > 10) {
        log('Visibility change detected on list page, checking page size...');
        await ensurePageSize();
      }
      scheduleNextProduct(800);
    }
  }
});

// Expose for debugging
window.__pddLearning = {
  startExtraction,
  extractCheckedProducts,
  extractDetailPageContent,
  handleDetailPage,
  continueAfterBack,
  state
};
