from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Menu, Tenant
from .decorators import tenant_owner_required
from .forms import MenuForm

@tenant_owner_required
def owner_menu_list_by_tenant(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # テナントオブジェクトが正しくcontextに渡されているか確認
    context = {
        'tenant': tenant,  # これが重要
        'menus': Menu.objects.filter(tenant=tenant),
    }
    return render(request, 'reservations/owner_menu_list.html', context)

@login_required
def owner_menu_list(request):
    tenant = Tenant.objects.filter(owner=request.user).first()
    if not tenant:
        return render(request, 'reservations/owner_no_tenant.html')
    menus = Menu.objects.filter(tenant=tenant)
    return render(request, 'reservations/owner_menu_list.html', {
        'tenant': tenant,
        'menus': menus,
    })

@login_required
def owner_menu_add(request):
    tenant = Tenant.objects.filter(owner=request.user).first()
    if not tenant:
        return render(request, 'reservations/owner_no_tenant.html')
    if request.method == 'POST':
        form = MenuForm(request.POST)
        if form.is_valid():
            menu = form.save(commit=False)
            menu.tenant = tenant
            menu.save()
            return redirect('owner_menu_list')
    else:
        form = MenuForm()
    return render(request, 'reservations/owner_menu_form.html', {'form': form, 'tenant': tenant, 'mode': 'add'})

@login_required
def owner_menu_edit(request, menu_id):
    tenant = Tenant.objects.filter(owner=request.user).first()
    menu = get_object_or_404(Menu, id=menu_id, tenant=tenant)
    if request.method == 'POST':
        form = MenuForm(request.POST, instance=menu)
        if form.is_valid():
            form.save()
            return redirect('owner_menu_list')
    else:
        form = MenuForm(instance=menu)
    return render(request, 'reservations/owner_menu_form.html', {'form': form, 'tenant': tenant, 'mode': 'edit'})

@login_required
def owner_menu_delete(request, menu_id):
    tenant = Tenant.objects.filter(owner=request.user).first()
    menu = get_object_or_404(Menu, id=menu_id, tenant=tenant)
    if request.method == 'POST':
        menu.delete()
        return redirect('owner_menu_list')
    return render(request, 'reservations/owner_menu_confirm_delete.html', {'menu': menu, 'tenant': tenant})
