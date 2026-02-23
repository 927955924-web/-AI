/**
 * Qianniu (Taobao) Learning Preload Script
 * Extracts product information from Taobao/Tmall seller backend for knowledge base learning
 * 
 * Flow:
 * 1. On list page: identify checked products, click title to open detail page
 * 2. On detail page: scroll page, extract content, notify main process
 * 3. Main process: navigate back, continue to next product
 */
const { ipcRenderer } = require('electron');

const PLATFORM_ID = 'qianniu';

// State management
const state = {
  isExtracting: false,
  extractedProducts: [],
  pendingProducts: [],
  currentProductIndex: 0,
  totalProducts: 0,
  listPageUrl: '',
  isOnDetailPage: false
};

/**
 * Log message to main process
 */
function log(message, level = 'info') {
  console.log(`[Learning-QN][${level}] ${message}`);
  ipcRenderer.send('learning:log', { platform: PLATFORM_ID, message, level });
}

/**
 * Sleep helper
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Smooth scroll the page to trigger lazy loading
 */
async function scrollPage() {
  const scrollHeight = document.documentElement.scrollHeight;
  const viewportHeight = window.innerHeight;
  const scrollStep = viewportHeight * 0.8;
  
  for (let scrollPos = 0; scrollPos < scrollHeight; scrollPos += scrollStep) {
    window.scrollTo({ top: scrollPos, behavior: 'smooth' });
    await sleep(300);
  }
  
  window.scrollTo({ top: scrollHeight, behavior: 'smooth' });
  await sleep(500);
  
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
  return url.includes('/item/') || 
         url.includes('item_id=') ||
         url.includes('/product/detail') ||
         document.querySelector('[class*="item-detail"], [class*="product-detail"]');
}

/**
 * Check if current page is the product list page
 */
function isListPage() {
  const url = window.location.href;
  return url.includes('/item/list') || 
         url.includes('/goods/list') ||
         url.includes('/product-list') ||
         document.querySelector('table tbody tr [class*="item-title"]');
}

/**
 * Extract product list from current page (only checked rows)
 */
function extractCheckedProducts() {
  const products = [];
  
  const productRows = findElements([
    'tr[class*="J_item"]',
    '[class*="item-basic"]',
    '[class*="goods-item"]',
    '[class*="product-row"]',
    '.item-mod__item',
    'table tbody tr',
    '[class*="bp-table"] tr',
  ]);
  
  log(`Found ${productRows.length} product rows on page`);
  
  // Filter to only checked rows
  const checkedRows = productRows.filter(row => {
    const tr = row.closest('tr') || row;
    if (tr.closest('thead') || tr.querySelector('th')) {
      return false;
    }
    const firstCell = tr.querySelector('td:first-child, td');
    if (firstCell) {
      const checkbox = firstCell.querySelector(
        'input[type="checkbox"]:checked, ' +
        '.next-checkbox-checked, ' +
        '.ant-checkbox-checked, ' +
        '.ant-checkbox-wrapper-checked, ' +
        '[class*="checkbox-checked"]'
      );
      if (checkbox) return true;
    }
    return tr.querySelector('td .next-checkbox-checked, td .ant-checkbox-checked, td input[type="checkbox"]:checked');
  });
  
  if (checkedRows.length === 0) {
    log('No products checked', 'warn');
    return [];
  }
  
  log(`Found ${checkedRows.length} checked products`);
  
  checkedRows.forEach((row, index) => {
    try {
      const titleLink = row.querySelector(
        'a[href*="item"], ' +
        'a[href*="detail"], ' +
        '[class*="item-title"] a, ' +
        '[class*="goods-name"] a, ' +
        '.item-basic-info a'
      );
      
      if (!titleLink) {
        log(`Row ${index}: No title link found, skipping`, 'warn');
        return;
      }
      
      let productId = '';
      if (titleLink.href) {
        const idMatch = titleLink.href.match(/[?&](?:item_id|id)=(\d+)/);
        if (idMatch) productId = idMatch[1];
      }
      if (!productId) {
        productId = row.dataset.itemid || row.dataset.id || `tb_${index}`;
      }
      
      const name = getText(titleLink) || '未知商品';
      
      const priceEl = row.querySelector('[class*="price"], [class*="sale-price"]');
      const price = priceEl ? getText(priceEl).replace(/[^\d.]/g, '') : '0';
      
      const stockEl = row.querySelector('[class*="stock"], [class*="inventory"], [class*="num"]');
      const stock = stockEl ? getText(stockEl).replace(/[^\d]/g, '') : '0';
      
      const imgEl = row.querySelector('img[src*="taobao"], img[src*="alicdn"], img');
      const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';
      
      products.push({
        platform_product_id: productId,
        name: name,
        price: parseFloat(price) || 0,
        stock: parseInt(stock) || 0,
        image_url: imageUrl,
        detail_url: titleLink.href,
        platform: PLATFORM_ID,
        rowIndex: index,
        titleLinkHref: titleLink.href
      });
      
      log(`Row ${index}: ${name.substring(0, 30)}...`);
      
    } catch (e) {
      log(`Error extracting row ${index}: ${e.message}`, 'error');
    }
  });
  
  return products;
}

/**
 * Click on product title link
 */
function clickProductTitle(targetHref) {
  const allLinks = document.querySelectorAll('a[href*="item"], a[href*="detail"]');
  for (const link of allLinks) {
    if (link.href === targetHref) {
      log(`Clicking title link: ${targetHref.substring(0, 60)}...`);
      link.click();
      return true;
    }
  }
  log(`Could not find link with href: ${targetHref}`, 'error');
  return false;
}

/**
 * Extract product detail from current detail page
 */
async function extractDetailPageContent() {
  log('Extracting detail page content...');
  
  await scrollPage();
  await sleep(500);
  
  const detail = {
    description: '',
    specs: {},
    images: []
  };
  
  // Extract title
  const titleEl = findElement([
    '[class*="item-title"]',
    '[class*="product-title"]',
    '[class*="goods-name"]',
    'h1', 'h2'
  ]);
  const title = getText(titleEl);
  
  // Extract description
  const descEl = findElement([
    '[class*="item-desc"]',
    '[class*="description"]',
    '[class*="detail-content"]',
    '#desc-content',
    '[class*="detail-desc"]',
  ]);
  if (descEl) {
    detail.description = getText(descEl).substring(0, 3000);
  }
  
  if (!detail.description && title) {
    detail.description = title;
  }
  
  // Extract all text from main content
  const mainContent = findElement([
    '[class*="item-detail"]',
    '[class*="product-detail"]',
    'main', '#app'
  ]);
  if (mainContent && detail.description.length < 500) {
    const allText = getText(mainContent).substring(0, 3000);
    if (allText.length > detail.description.length) {
      detail.description = allText;
    }
  }
  
  // Extract specifications
  const specRows = findElements([
    '[class*="prop-item"]',
    '[class*="attr-item"]',
    '[class*="sku-prop"]',
    '.props-item',
    '#J_AttrUL li',
    'table[class*="prop"] tr',
  ]);
  
  specRows.forEach(row => {
    const labelEl = row.querySelector('[class*="label"], [class*="name"], th');
    const valueEl = row.querySelector('[class*="value"], [class*="content"], td');
    let label = getText(labelEl);
    let value = getText(valueEl);
    
    if (!label && !value) {
      const text = getText(row);
      const match = text.match(/^([^:：]+)[：:](.+)$/);
      if (match) {
        label = match[1].trim();
        value = match[2].trim();
      }
    }
    
    if (label && value && label !== value) {
      detail.specs[label] = value;
    }
  });
  
  // Extract SKU options
  const skuOptions = findElements([
    '[class*="sku-item"]',
    '[class*="sale-prop"]',
    '[class*="spec-item"]',
    '.J_Prop',
  ]);
  if (skuOptions.length > 0) {
    detail.specs['规格选项'] = skuOptions.map(v => getText(v)).filter(Boolean).join(', ');
  }
  
  // Extract images
  const images = findElements([
    '[class*="gallery"] img',
    '[class*="slider"] img',
    'img[src*="taobao"]',
    'img[src*="alicdn"]',
  ]);
  images.forEach(img => {
    const src = img.src || img.dataset.src;
    if (src && !detail.images.includes(src)) {
      detail.images.push(src);
    }
  });
  
  log(`Extracted: description(${detail.description.length} chars), specs(${Object.keys(detail.specs).length}), images(${detail.images.length})`);
  
  return detail;
}

/**
 * Main extraction process
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
  
  log('Starting product extraction for Qianniu/Taobao...');
  log(`List page URL: ${state.listPageUrl}`);
  ipcRenderer.send('learning:started', { platform: PLATFORM_ID });
  
  try {
    const products = extractCheckedProducts();
    
    if (products.length === 0) {
      ipcRenderer.send('learning:error', {
        platform: PLATFORM_ID,
        error: '请先勾选需要学习的商品，再点击开始学习'
      });
      state.isExtracting = false;
      return;
    }
    
    state.pendingProducts = products;
    state.totalProducts = products.length;
    
    log(`Found ${products.length} products to learn`);
    
    ipcRenderer.send('learning:progress', {
      platform: PLATFORM_ID,
      phase: 'listing',
      extracted: products.length,
      message: `已识别 ${products.length} 个商品，开始获取详情...`
    });
    
    await sleep(500);
    processNextProduct();
    
  } catch (error) {
    log(`Extraction error: ${error.message}`, 'error');
    ipcRenderer.send('learning:error', {
      platform: PLATFORM_ID,
      error: error.message
    });
    state.isExtracting = false;
  }
}

/**
 * Process next product in the queue
 */
function processNextProduct() {
  if (!state.isExtracting) {
    log('Extraction stopped');
    return;
  }
  
  if (state.currentProductIndex >= state.pendingProducts.length) {
    log('All products processed, sending to backend');
    ipcRenderer.send('learning:products-extracted', {
      platform: PLATFORM_ID,
      products: state.extractedProducts,
      totalCount: state.extractedProducts.length
    });
    state.isExtracting = false;
    return;
  }
  
  const product = state.pendingProducts[state.currentProductIndex];
  log(`Processing product ${state.currentProductIndex + 1}/${state.totalProducts}: ${product.name.substring(0, 30)}...`);
  
  ipcRenderer.send('learning:progress', {
    platform: PLATFORM_ID,
    phase: 'detail',
    current: state.currentProductIndex + 1,
    total: state.totalProducts,
    productName: product.name,
    message: `正在学习商品详情 (${state.currentProductIndex + 1}/${state.totalProducts}): ${product.name.substring(0, 25)}...`
  });
  
  if (!clickProductTitle(product.titleLinkHref)) {
    log(`Skipping product ${state.currentProductIndex + 1} - could not click title`);
    state.currentProductIndex++;
    setTimeout(processNextProduct, 500);
  }
}

/**
 * Handle detail page - extract content and go back
 */
async function handleDetailPage() {
  if (!state.isExtracting || state.currentProductIndex >= state.pendingProducts.length) {
    return;
  }
  
  log('Detail page loaded, extracting content...');
  state.isOnDetailPage = true;
  
  const product = state.pendingProducts[state.currentProductIndex];
  
  try {
    await sleep(1000);
    const detail = await extractDetailPageContent();
    
    const fullProduct = {
      ...product,
      description: detail.description,
      specs: detail.specs,
      images: detail.images
    };
    
    delete fullProduct.rowIndex;
    delete fullProduct.titleLinkHref;
    
    state.extractedProducts.push(fullProduct);
    log(`Product ${state.currentProductIndex + 1} extracted successfully`);
    
  } catch (err) {
    log(`Error extracting detail: ${err.message}`, 'error');
    state.extractedProducts.push({
      ...product,
      description: '',
      specs: {}
    });
  }
  
  state.currentProductIndex++;
  state.isOnDetailPage = false;
  
  log('Going back to list page...');
  ipcRenderer.send('learning:navigate-back', {
    platform: PLATFORM_ID,
    listPageUrl: state.listPageUrl,
    nextIndex: state.currentProductIndex,
    total: state.totalProducts
  });
}

/**
 * Continue processing after returning to list page
 */
function continueAfterBack() {
  log('Back on list page, continuing...');
  setTimeout(() => {
    if (state.isExtracting) {
      processNextProduct();
    }
  }, 1000);
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

// Initialize
window.addEventListener('DOMContentLoaded', async () => {
  log('Learning preload script loaded for Qianniu/Taobao');
  log(`Current URL: ${window.location.href}`);
  
  await sleep(500);
  
  if (isDetailPage() && state.isExtracting && state.isOnDetailPage === false) {
    log('Detected detail page during extraction');
    handleDetailPage();
  }
  
  ipcRenderer.send('learning:ready', { platform: PLATFORM_ID });
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && state.isExtracting) {
    if (isDetailPage()) {
      handleDetailPage();
    } else if (isListPage()) {
      continueAfterBack();
    }
  }
});

// Expose for debugging
window.__qnLearning = {
  startExtraction,
  extractCheckedProducts,
  extractDetailPageContent,
  handleDetailPage,
  continueAfterBack,
  state
};
